# tour.json schema

One JSON object with five keys. Only `meta` and `days` are required.

```json
{
  "meta":       { },
  "labels":     { },
  "map":        { },
  "markets":    { },
  "properties": [ ],
  "days":       [ ]
}
```

`null` means **to be confirmed** and renders as such, in italic sage. Never
write a guess where you mean `null`.

---

## meta

| field | req | notes |
|---|---|---|
| `title` | yes | Hero headline, e.g. `"Normal Bratislava Tour"` |
| `titleEm` | | Substring of `title` shown in accent green. Must appear verbatim in `title`. |
| `appTitle` | | Home-screen name when saved to a phone. Keep short. |
| `documentTitle` | | Browser tab text. Defaults to `title · dateRange`. |
| `subtitle` | | Line under the accent bar, e.g. region |
| `dateRange` | | e.g. `"26 August 2026"` |
| `wordmark` | | Top-left mark. Defaults to `CBRE`. |
| `lang` | | Defaults to `en`. Sets `<html lang>`. |
| `compiled` | | Date the pack was compiled, shown in the footer |
| `copyright` | | Footer line, e.g. `"(c) 2026 CBRE"` |
| `disclaimer` | | Footer paragraph. **Include this on anything client-facing.** |
| `kpis` | | Explicit stat band, see below. Omit to auto-compute. |

If neither `disclaimer` nor `copyright` is set, the footer band is hidden
entirely rather than rendering as an empty dark bar.

### meta.kpis

Omit and the runtime computes a sensible band: days (or the date, on a
one-day tour), stops, properties, and markets when there is more than one.
Override when the client cares about something else:

```json
"kpis": [
  { "label": "Date",  "value": "Wed 26 Aug", "sub": "Wednesday" },
  { "label": "Stops", "value": "6",           "sub": "Scheduled" },
  { "label": "Area",  "value": "60 - 76k",    "sub": "sq m range" }
]
```

Values longer than 6 characters automatically drop to a smaller type size.

---

## map

All optional.

```json
"map": { "style": "osm", "route": true, "height": "tall" }
```

| field | default | notes |
|---|---|---|
| `style` | `osm` | `osm`, `osm-grey`, `esri-street`, `esri-grey` |
| `route` | `true` | dashed line through the stops in running order |
| `height` | | `"tall"` for a taller map box |
| `tiles` | | explicit tile URL template, overrides `style` |
| `attribution` | | required if you set `tiles` |
| `maxZoom` | per style | |
| `desaturate` | per style | CSS-filter the tile pane towards grey |

---

## markets

Keyed by a short code. Used to group the options view and label properties.
Declaration order is the display order.

```json
"markets": {
  "sk": {
    "name": "Slovakia",
    "code": "SK",
    "sub":  "Bratislava and Zitny ostrov",
    "pack": "Normal Options, Bratislava, 5 August 2026"
  }
}
```

`pack` is the source document, printed under the market heading. It is how a
reader knows which pack a number came from; fill it in.

---

## properties

One entry per property, referenced from stops by `id`.

| field | req | notes |
|---|---|---|
| `id` | yes | unique, e.g. `"sk4"`. Stops reference this. |
| `name` | yes | |
| `market` | | key into `markets` |
| `no` | | option number, shown as `Opt 4` |
| `tour` | | `true` if visited. Options view chips on/off tour. |
| `city` | | |
| `region` | | |
| `dev` | | developer or landlord; becomes the first chip |
| `lat`, `lng` | | decimal degrees. **Both or neither.** |
| `mapsUrl` | | explicit link; wins over `lat`/`lng` |
| `query` | | text fallback for the Maps link |
| `size` | | headline area chip, e.g. `"60,409 sq m"` |
| `rent` | | headline rent chip |
| `desc` | | Overview paragraph in the detail sheet |
| `facts` | | `[[label, value], ...]` Specification table |
| `terms` | | `[[label, value], ...]` Commercial terms table |
| `chips` | | extra chips, array of strings |
| `docs` | | see below |

```json
{
  "id": "sk5", "market": "sk", "no": 5, "tour": true,
  "name": "VGP Park Triblavina", "city": "Chorvatsky Grob", "dev": "VGP",
  "lat": 48.221847, "lng": 17.264919,
  "size": "60,409 sq m", "rent": "EUR 61 / sq m",
  "desc": "Two halls on the D1 at the Triblavina interchange...",
  "facts": [["Status", "Existing"], ["Clear height", "12 m"], ["BREEAM", null]],
  "terms": [["Lease term", "10 years"], ["Rent free", null]],
  "docs":  [{ "label": "Brochure", "href": "brochures/vgp.pdf", "size": "2.1 MB" }]
}
```

### docs

`href` is used as given. A relative path only resolves if the file travels
with the HTML, which defeats the single-file design, so prefer an absolute
SharePoint or Worker URL for anything you send out.

---

## days

```json
{
  "id": "d1", "n": 1, "date": "2026-08-26", "dow": "Wednesday",
  "label": "Wed 26 Aug", "title": "Wed 26 Aug",
  "region": "Slovakia, Bratislava and Zitny ostrov",
  "market": "sk",
  "note": "The day opens at Triblavina, runs east to the Zitny ostrov stops...",
  "stops": [ ]
}
```

| field | req | notes |
|---|---|---|
| `date` | | `YYYY-MM-DD`. Drives the countdown and today-highlighting. Omit and both stop working. |
| `n` | | day number; defaults to position |
| `dow` | | weekday name, shown in the eyebrow |
| `label` | | short pill text, e.g. `"Wed 26 Aug"` |
| `title` | | big day heading; falls back to `label` |
| `region` | | shown in the day meta line |
| `note` | | the paragraph under the heading. Write what shape the day has, not a list of the stops. |
| `stops` | yes | |

On a one-day tour the day pills are hidden and the eyebrow leads with the
weekday and region rather than "Day 1".

### stops

| field | req | notes |
|---|---|---|
| `t` | | time text, free form: `"09:40 - 09:50"`, `"En route"`, `"Evening, tbc"` |
| `name` | yes* | *or `prop`, which supplies the name |
| `kind` | | `view` (default with a prop), `travel`, `meal`, `meet`. Sets the card's left border and pin colour. |
| `prop` | | property id. Makes the card tappable and puts a pin on the map. |
| `also` | | second property discussed at the same stop; adds a second Maps button |
| `note` | | one or two sentences |
| `attend` | | `true` -> "Developer attending" chip; `"tbc"` -> "Attendance tbc" |
| `tbc` | | `true` -> "To confirm" chip |
| `lat`, `lng` | | override the property's coordinates for this stop |
| `query` | | text for the Maps link when there is no prop |
| `chips` | | extra chips |

```json
{ "t": "11:20 - 12:00", "name": "BHM Dunajska Streda",
  "kind": "view", "prop": "sk7", "attend": true,
  "note": "Full viewing." }
```

Pin numbers follow **position in the day**, not position among mapped stops.
A stop with no coordinates leaves a gap in the numbering rather than
silently renumbering the rest, so the cards and the map always agree.

---

## What the build checks

Fatal (nothing is written):

- missing `meta.title`, empty `days`
- duplicate or missing property `id`
- a stop referencing an unknown `prop` or `also`
- only one of `lat`/`lng`, non-numeric, or out of range
- a malformed `facts` / `terms` row
- a non-ISO `date`
- a stop with neither `name` nor `prop`

Warnings (the gap report; `--strict` makes them fatal):

- a day with no mappable stop, or a count of stops missing coordinates
- a property with no coordinates, link, query or city
- a property flagged `tour: true` that no stop visits
- an unknown `market` or `kind`
- a day with no `date` or no stops, or two days sharing a date
