# Source playbook (per country)

This file is the concrete antidote to shallow research. "Search in the local language and go deep" is meaningless without knowing the local warehouse vocabulary and where the real data lives. Hand each research subagent the sections for the countries in its batch.

Do not hardcode the exact portal URLs from this file into a search; portal names and addresses change. Use the named source *types* and *vocabulary* to drive searches, and let the agent find the current portal. The agent should always run searches in English and in the listed local language(s).

## How to use each country section

For every country, run the loop: company's own disclosures, then planning/permit portals, then the commercial register, then trade press, then property listings, then local news, then the 3PL cross-search. Aim for several independent source types per site, not a single hit. Job postings are a signal that a site exists, never the sole source for a size or landlord.

A note on planning portals: building permits and zoning applications are often the single richest source for size, developer and build year, because a warehouse cannot be built without them and they state floor area and the developer. They are usually local-language only. This is where depth is won.

---

## Netherlands

- **Local terms:** magazijn, distributiecentrum (DC), logistiek centrum, fulfilmentcentrum, opslagloods, koel- en vrieshuis (cold/frozen store), cross-dock, e-fulfilment.
- **High-value sources:** company annual report and "onze vestigingen" / "locaties" pages; the national planning portal for omgevingsvergunning (environmental/building permits) and bestemmingsplan (zoning); the Kamer van Koophandel (KvK) commercial register for entities and registered addresses; logistics trade press (Logistiek.nl, Nieuwsblad Transport, Vastgoedmarkt for the property angle); regional development agencies; local newspapers covering new-build announcements.
- **Hotspots to check:** Venlo and the wider Limburg corridor, Tilburg/Waalwijk, Rotterdam port area, Schiphol/Amsterdam, Moerdijk, Almere/Lelystad.

## Germany

- **Local terms:** Lager, Lagerhaus, Logistikzentrum, Distributionszentrum, Verteilzentrum, Logistikimmobilie, Kühllager / Tiefkühllager (cold/frozen), Umschlaglager (cross-dock), Fulfillment-Center.
- **High-value sources:** Geschäftsbericht (annual report) and "Standorte" pages; Bauantrag / Bebauungsplan (building permit / zoning) via municipal and Land planning portals; Handelsregister / Unternehmensregister for entities; logistics and property trade press (DVZ Deutsche Verkehrs-Zeitung, Logistik Heute, Immobilien Zeitung, Thomas Daily); IHK regional chambers; local press for ground-breaking and opening announcements.
- **Hotspots:** the logistics regions around Hamburg, the Rhein-Ruhr and Rhein-Main areas, Leipzig/Halle, Nuremberg, Kassel (geographic centre, common for national DCs), Berlin-Brandenburg.

## Belgium

- **Local terms (Dutch):** magazijn, distributiecentrum, logistiek centrum; **(French):** entrepôt, plateforme logistique, centre de distribution, magasin logistique; koelopslag / entrepôt frigorifique (cold).
- **High-value sources:** company disclosures; the omgevingsvergunning (Flanders) and permis d'environnement / permis d'urbanisme (Wallonia/Brussels) permit systems; the Kruispuntbank van Ondernemingen / Banque-Carrefour des Entreprises (KBO/BCE) company register; trade press (Flows, Made in, Gondola for retail logistics); regional development agencies. Belgium is bilingual, so search both Dutch and French.
- **Hotspots:** the Antwerp port and the Antwerp-Brussels axis, the Genk/Limburg corridor, Liege (a major e-commerce and air-cargo hub), Ghent, Wallonia's logistics parks along the E42.

## France

- **Local terms:** entrepôt, plateforme logistique, centre de distribution, base logistique, entrepôt frigorifique (cold store), centre de tri (sorting/cross-dock), centre de e-commerce.
- **High-value sources:** rapport annuel and "nos sites" / "implantations" pages; ICPE filings (Installations Classees pour la Protection de l'Environnement), which warehouses above a threshold must lodge and which state surface area and operator; permis de construire (building permit); the registre du commerce (Infogreffe / societe.com) for entities; trade press (Voxlog, Stratégies Logistique, Supply Chain Magazine, Business Immo for the property angle).
- **Hotspots:** the "dorsale logistique" from Lille through Paris/Ile-de-France to Lyon and Marseille; the Lyon corridor (Plaine de l'Ain, Isle d'Abeau); Orleans; the Nord around Lille; the Marseille/Fos port area.

## Spain

- **Local terms:** almacén, centro de distribución, centro logístico, plataforma logística, nave logística, almacén frigorífico (cold), centro de fulfilment.
- **High-value sources:** informe anual and "centros" / "instalaciones" pages; the licencia de actividad / licencia urbanística (municipal activity and planning licences); the Registro Mercantil for entities; trade press (Cadena de Suministro, Logística Profesional, El Mercantil); the property press (Brainsre, Ejeprime). Regional governments publish industrial-land and logistics-park information.
- **Hotspots:** the Madrid "Corredor del Henares" (Coslada, San Fernando, Azuqueca, Guadalajara); Catalonia around Barcelona (El Prat, the A2 corridor); Valencia and Zaragoza (PLAZA, a major inland logistics platform); Seville.

## Italy

- **Local terms:** magazzino, centro di distribuzione, polo logistico, piattaforma logistica, centro logistico, magazzino refrigerato (cold), hub di smistamento (sorting).
- **High-value sources:** bilancio (annual report) and "sedi" / "stabilimenti" pages; permesso di costruire and the SUAP (one-stop business desk) filings; the Registro delle Imprese (Camera di Commercio) for entities; trade press (Logistica Management, Trasporto Europa, Supply Chain Italy; Monitorimmobiliare for property).
- **Hotspots:** the "logistics triangle" of Lombardy/Piacenza/Novara in the north; the Bologna and wider Emilia corridor along the A1; Verona (Quadrante Europa, a major interport); Rome and the Lazio plains; Naples/Nola interport in the south.

## Poland

- **Local terms:** magazyn, centrum dystrybucyjne, centrum logistyczne, hala magazynowa, magazyn chłodniczy (cold), centrum realizacji zamówień / fulfilment, sortownia (sorting).
- **High-value sources:** raport roczny and "lokalizacje" pages; the pozwolenie na budowę (building permit) and miejscowy plan zagospodarowania (local zoning); the KRS (Krajowy Rejestr Sądowy) company register; trade press (Trans.info, Log24, Eurologistics; Propertynews and Eurobuild for the warehouse property market, which in Poland is very well documented by the big developers).
- **Hotspots:** Greater Warsaw (especially the A2 west of the city); Łódź (the geographic centre, dense with big-box DCs); Upper Silesia around Katowice; Poznań on the A2; Wrocław in the south-west; the "Eastern" zone near the Belarus/Ukraine borders for cross-border flows. Poland's warehouse market is developer-led, so the major industrial developers' own leasing announcements are a strong source.

## Generic template for other countries

For any market not listed above (Czechia, Slovakia, Hungary, Romania, Portugal, the Nordics, Ireland, Austria, Switzerland, and others), build the same structure before dispatching:

1. **Local warehouse vocabulary.** The words for warehouse, distribution centre, logistics centre, fulfilment centre, cold store and cross-dock in the local language(s). Search all of them.
2. **The permit/planning system.** Find the local building-permit and zoning system; it is almost always the richest source for floor area, developer and build year, and almost always local-language only.
3. **The commercial register.** The national company register for legal entities and registered addresses.
4. **Logistics and property trade press.** The local supply-chain and warehouse-property publications.
5. **The major 3PLs in that market** (see below), for the cross-search.

## Major 3PL operators, and how to surface their sites

A large share of any occupier's warehouses are run by these providers and appear under the *provider's* name, or only in the press, never under the occupier's. Surfacing them is the difference between a half-map and a real one. Run two search directions for each provider the occupier is known or likely to use, in English and the local language:

1. **The contract-win announcement.** Providers press-release their wins and trade press republishes them, so search the *event* with verbs rather than the two company names: "[provider] opens / launches / new warehouse / new DC / to operate / awarded / wins / go-live / fulfilment for [occupier]", plus the reverse "[occupier] appoints / selects / outsources to / partners with [provider]" and "[occupier] distribution centre operated by". Example shape: "Kuehne+Nagel opens warehouse for [occupier]" surfaces the site, its location and often its size from a single release, where "[occupier] + Kuehne+Nagel" returns nothing useful.
2. **The provider's customer case studies.** Providers publish reference stories on their own sites ("customer stories", "case studies", "references") that name the client and frequently the exact site, size and function. High value, under-searched.

When an announcement names a site, the operator is the provider and the occupier is the client, so the site belongs in the occupier's map. Date the announcement: an old contract may have ended, so corroborate anything more than two or three years old against a recent source and set the record's "last confirmed" year accordingly. The announcement gives operator and location, rarely the building's owner, so the landlord still comes from the property and planning angle.

Providers to cross-search:

DHL Supply Chain, Kuehne+Nagel, DSV, GXO Logistics, DB Schenker, CEVA Logistics, Geodis, ID Logistics, FM Logistic, Rhenus, Wincanton, Dachser, Maersk (Contract Logistics), XPO, Bollore (where still operating), Arvato/Bertelsmann (e-commerce fulfilment), Fiege, Nagel-Group (food/cold chain), STEF (cold chain, France/Southern Europe), NewCold and Lineage (specialist cold storage), Yusen Logistics, Kerry Logistics.

This list is a starting point. The Stage 1 profile should add any provider named in the company's own filings, which is the strongest signal of an actual relationship.
