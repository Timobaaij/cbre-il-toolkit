---
name: cbre-site-tour-app
description: Build a self-contained, CBRE-branded interactive HTML SITE TOUR / ITINERARY web app from tour inputs (an agenda or schedule, coordinates, Google Maps links, and optionally Excel availability sheets, PDF or PPTX brochures and emails). Produces ONE portable .html file: a day-by-day timeline where every day opens on an embedded Leaflet map with the stops numbered in running order, plus tap-through property detail, Google Maps deep links, copyable coordinates and an all-options list. Mobile-first for use in the field, with a true desktop layout (sticky map beside the timeline) on a laptop. Styled to match the CBRE longlist dashboard: Financier Display, Calibre, Space Mono, CBRE green and accent, 2px radius. Handles one-day tours as well as multi-day. Use whenever the user wants to build a tour app, a site visit schedule, an itinerary web app, a tour agenda page, a "what are we seeing on Tuesday" app, or wants to turn a schedule plus coordinates into a website; also to update or restyle an existing tour app. Trigger even when the need is only described (make the app for next week's site visits; turn this agenda into a phone app for the client).
---

# CBRE Site Tour App

Turns a tour agenda plus property data into **one self-contained, CBRE-branded
HTML web app**. No build step for the user, no CDN, no server: a single file
they can email, drop in SharePoint, or serve from a Cloudflare Worker.

**The output is data-driven.** You do not hand-write HTML. You write a
`tour.json` and run `build_tour.py`, which injects it into a fixed, tested
template. That is what keeps every tour visually identical to the last and
stops the layout regressing each time someone asks for a change.

## The loop

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise it is silent); it does nothing but a single public version lookup, never blocks the build, and is safe to ignore.


1. **Gather** the inputs into `work/` (agenda text, Excel, brochures, emails).
2. **Write `tour.json`** against `reference/data-schema.md`. This is the only
   creative step: everything else is mechanical.
3. **Build**: `python scripts/build_tour.py tour.json -o "Tour.html"`
4. **Read the warnings.** They are the gap report. Fix the data, not the HTML.
5. **Open the file** and check it at phone width and desktop width.

```bash
python scripts/build_tour.py tour.json -o "Client Tour.html"
```

## Hard rules

- **Never edit the generated .html to fix content.** Change `tour.json` and
  rebuild. Hand-edits are lost on the next build and drift the house style.
- **Never invent a coordinate, a rent, a size or an attendance.** Unknown is
  `null`, which renders as "To be confirmed". A wrong pin sends a client to
  the wrong field; "tbc" only costs them a phone call.
- **Every stop that can be placed must have `lat`/`lng`.** The map is the
  point of the app. The build warns per day when stops are unplaceable.
- **Do not add a second view, a new colour, or a new font.** The design is
  inherited from the CBRE longlist dashboard on purpose. If a change is
  genuinely needed, change `assets/tour_template.html` so every future tour
  gets it too, and say so.
- **Resolve `maps.app.goo.gl` short links before using them.** They carry no
  coordinates until followed. See "Coordinates" below.

## What the output does

| | |
|---|---|
| **Schedule view** | One day at a time. Day head, then the day's map, then the timeline. Day pills switch days; hidden entirely on a one-day tour. |
| **Day map** | Embedded Leaflet. Stops numbered in running order, dashed route between them, popups with a Google Maps link and a Details button. Tapping a card's pin number pans the map to it. |
| **Options view** | Every property, grouped by market, searchable, flagged on/off tour. |
| **Detail sheet** | Overview, specification, commercial terms, documents. Bottom sheet on a phone, centred dialog on desktop. |
| **Per stop** | Google Maps deep link and a copy-coordinates button. |
| **KPI band** | Auto-computed (days or date, stops, properties, markets) or set explicitly via `meta.kpis`. |

Layout is genuinely responsive, not a scaled phone page:

- **< 720px** single column, bottom tab bar, map above the timeline.
- **720-1023px** the same column, roomier.
- **>= 1024px** full-bleed green hero, inline tabs, and a two-column day:
  timeline left, **sticky map right**.

## Coordinates

Coordinates are the one thing worth being pedantic about.

- A `https://maps.app.goo.gl/...` link contains no coordinates. Resolve it:
  ```bash
  curl -sIL "https://maps.app.goo.gl/XXXX" | grep -i '^location:' | head -1
  ```
  The redirect target holds `/maps/search/48.497696,+17.030514`. Use those
  numbers as `lat`/`lng`; keep the original link in `mapsUrl` only if the
  client asked for that exact link.
- Prefer coordinates over a text `query`. Warehouse schemes and greenfield
  plots frequently have no searchable address, so a name search drops the pin
  in the wrong town.
- Order of precedence used by the runtime: `mapsUrl` -> `lat`/`lng` ->
  `query` -> `name, city`.

## Basemaps

Default is `osm`: the standard OpenStreetMap Leaflet style, which is the
streets map (roads and labels, not satellite or topographic). No API key.
Set `map.style` in `tour.json` to change it:

| style | look | note |
|---|---|---|
| `osm` | OpenStreetMap standard streets | **default**; no third-party terms to weigh |
| `osm-grey` | the same tiles, near-greyscale | quieter under green pins |
| `esri-street` | Esri World Street Map | closest to default Google Maps |
| `esri-grey` | very quiet grey canvas | pins dominate; maxZoom 16 |

**CARTO is deliberately not offered.** Its free tier now requires an API key
and stamps a watermark on the tiles, which is not acceptable on a client
artefact. If a project has a paid key, set `map.tiles` and `map.attribution`
explicitly.

Two things to tell the user once, not to hide:

- **Tiles need a connection.** Everything else works offline. When tiles fail
  the map caption says so rather than showing a silent grey box.
- **Esri's keyless tiles** are served from `server.arcgisonline.com` under
  Esri's terms. Widely used, but if a client is strict about third-party
  terms, `osm-grey` avoids the question.

## Fonts and licensing

Calibre and Financier Display are **licensed CBRE brand fonts**, embedded
base64 (~470 KB) exactly as the CBRE longlist dashboard does. Space Mono is
SIL OFL. This is fine for internal and client work in the same way the
dashboard already is. `--no-fonts` drops them for a smaller, off-brand file;
only use it for a quick layout check, never for a deliverable.

## Existing tour apps

To bring a hand-written tour app into this pipeline:

```bash
node scripts/import_legacy_tour.js old-index.html > tour.json
```

It lifts the legacy top-level `PROPS` / `DAYS` / `MARKETS` arrays, promotes
attendance out of prose into `attend`, maps `terms` and `facts`, and derives
the size and rent chips. **Review `meta.*` by hand afterwards**: title,
subtitle, dateRange, disclaimer and compiled date are guessed from the
markup.

## Build flags

| flag | effect |
|---|---|
| `-o PATH` | output file (default `Tour.html`) |
| `--strict` | treat warnings as errors; use before shipping |
| `--no-map` | drop Leaflet, ~165 KB smaller, no day maps |
| `--no-fonts` | drop brand fonts; layout checks only |

Expect roughly **250 KB** without fonts, **730 KB** with them.

## Reference

Read these when the task needs them, not up front.

- `reference/data-schema.md` - every `tour.json` field, with worked examples.
- `reference/design-system.md` - the tokens, the component motifs, and what
  not to touch. Read before changing any CSS.
- `reference/ingestion.md` - getting data out of Excel, PDF and PPTX
  brochures, agenda emails and Google Maps links.
- `assets/example_tour.json` - a real one-day Bratislava tour. Build it to
  see a known-good output.

## Editing the template

The build fails loudly if a placeholder is left unfilled. One trap: never
write a build placeholder (double underscores around a capitalised word) as
literal text inside `assets/tour_runtime.js` or its own comments, because it
survives injection and trips that check.

`tour_runtime.js` must not declare a variable named `L`. Leaflet owns that
global, and shadowing it disables every map silently.
