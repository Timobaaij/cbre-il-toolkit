# Getting the data in

The build is mechanical. Reading the inputs is the part that needs judgement,
and it is where errors get baked into a client deliverable. Work source by
source and record where each number came from.

## Order of work

1. **Agenda first.** It defines the days, the running order and the times.
   Everything else hangs off it.
2. **Then coordinates**, because the map is the point of the app.
3. **Then property detail** from the availability sheet and brochures.
4. **Then documents**, if the client wants brochure links.

## Agenda text and emails

Agendas arrive as bullet lists in email. Read them literally.

```
* Blueprint Triblavina:            9:40 - 9:50
* VGP Triblavina:                  9:50 - 10:30 (Developer will be present)
* BHM Dunajska Streda:            11:20 - 12:00 (Developer will be present)
* Lunch in Bratislava:            14 - 15:30
```

- Normalise times to a consistent form: `"09:40 - 09:50"`. Keep `"En route"`
  and `"Evening, tbc"` as text when that is what the agenda says.
- `(Developer will be present)` becomes `"attend": true`, **not** prose in
  `note`. Attendance is a field so it renders as a chip and can be checked.
- "attendance to be confirmed" becomes `"attend": "tbc"`.
- A venue named only by town is `kind: "meal"` with a `query`, and the venue
  stays `null` / "to be confirmed". Do not pick a restaurant.
- **Re-check the running order against the clock.** A revised agenda often
  moves one stop and leaves the rest, which can make the day physically
  impossible. Flag tight legs to the user rather than silently accepting
  them: state the gap and the approximate distance.

## Coordinates

This is the highest-risk field in the file. A wrong pin sends a car to the
wrong field.

**Google Maps short links carry no coordinates.** Resolve the redirect:

```bash
curl -sIL "https://maps.app.goo.gl/AzRhwv8c6moCPbgc7" \
  | grep -i '^location:' | head -1
```

The target contains `/maps/search/48.497696,+17.030514`. Use those numbers as
`lat` / `lng`. Keep the short link in `mapsUrl` only if the client
specifically wants that link followed.

Rules:

- Prefer coordinates to a name search. Warehouse schemes and greenfield plots
  often have no searchable address.
- Sanity-check every pin against the stated city and country before shipping:
  a transposed digit lands you in the sea, and a swapped lat/lng lands you in
  Somalia.
- When a link only names a park with no pin, record `query` and leave
  `lat`/`lng` out. The build will warn, which is the correct outcome.
- Six decimal places is plenty. More is false precision.

## Excel availability sheets

```bash
python -c "
import openpyxl
wb = openpyxl.load_workbook('availability.xlsx', data_only=True)
for ws in wb:
    print('==', ws.title, ws.dimensions)
    for r in ws.iter_rows(max_row=6, values_only=True): print(r)
"
```

- `data_only=True` gives cached formula results. If they come back `None` the
  file was never opened in Excel and the formulas have no cached value; say
  so rather than reporting blanks as data.
- Brochure links usually live in **hyperlinks**, not cell text:
  `ws.cell(r, c).hyperlink.target`. The sibling skill
  `cbre-brochure-downloader` exists for pulling those down.
- Merged headers mean a header row spanning two rows. Read enough rows to
  work out the real column names before mapping anything.
- Keep the sheet's own units. If it says sq m, write sq m. Never convert
  silently.

## PDF and PPTX brochures

Use the `pdf` and `pptx` skills. Brochures are marketing documents:

- Take specification from the availability sheet where the two disagree, and
  note the disagreement. Brochures quote best-case clear heights and areas.
- A rent in a brochure is a headline asking rent. Label it as such.
- Do not lift brochure prose into `desc`. Write two or three factual
  sentences: where it is, what road it is on, what it suits, what stage it is
  at.

## Splitting facts from terms

Two tables render separately, and mixing them makes the sheet unreadable.

| `facts` (Specification) | `terms` (Commercial terms) |
|---|---|
| status, permitting, early access | lease term |
| warehouse / office / plot area | warehouse and office rent |
| divisible from, expansion | rent free, incentives |
| clear height, floor load | service charge |
| sprinklers, docks, doors | land price |
| parking, BREEAM | fit-out contribution |

Headline chips: `size` from the first `Warehouse area*` row, `rent` from
`Warehouse rent`, reduced to a short form like `"EUR 61 / sq m"`.

## Unknowns

Write `null`. It renders as "To be confirmed" in italic sage, which is a
useful prompt in a meeting. Blank strings, `"-"`, `"n/a"` and `"TBD"` all
look like sloppiness; a guess is worse than either.

## Before you ship

```bash
python scripts/build_tour.py tour.json -o "Client Tour.html" --strict
```

Then open it and check, at phone width and at desktop width:

- every day's map fits its stops, and the pin numbers match the cards
- the countdown reads sensibly for today's date
- the footer carries a disclaimer if this is going to a client
- tapping a card opens the right property
- the Maps button on two or three stops lands in the right place
