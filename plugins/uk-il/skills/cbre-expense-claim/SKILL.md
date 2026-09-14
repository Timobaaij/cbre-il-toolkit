---
name: cbre-expense-claim
description: Turn a folder of expense receipts (iOS scans, phone photos, Uber and airline email screenshots, AMEX and Revolut app screenshots) into a CBRE expense claim: a reconciled Expenses.xlsx and a page-stamped Consolidated Expenses.pdf, then file the lines into PeopleSoft. Use whenever the user wants their expenses done, receipts turned into a spreadsheet, a consolidated receipt PDF built, or an expense report prepared and filed. Trigger even when the need is only described ("do my expenses", "sort out last week's receipts", "turn this folder into a claim").
---

# CBRE expense claim

Two stages, each ending in a **hard stop**. Never roll past a stop. The
judgement calls that matter to the user happen in the gap between them.

```
1. Read receipts -> Excel + consolidated PDF  ==> STOP, they fill Expense Type
                                                    and Attendees in the Excel
2. Read those two columns back, file every    ==> STOP, hand back
   line in PeopleSoft, verify the total
```

The user then attaches the receipts and submits the report themselves. Do not
attach, and never fire Summary and Submit.

---

# Stage 1: read the receipts, build the two files

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a
one-line note to stderr *only* if a newer UK I&L Toolkit version has been published (otherwise
it is silent); it does nothing but a single public version lookup, never blocks the run, and is
safe to ignore.

## Inventory

Every PDF page and every image is a candidate page. A nine-page iOS scan is nine
candidates, not one. Read each one with vision; never infer an amount from a
filename. Filenames still help: `uber heen` and `uber terug` are Dutch for
outbound and return, which settles the direction of a taxi ride.

Classify each page:

| Class | What it looks like |
|---|---|
| `RECEIPT` | Any merchant document: thermal till roll, Polish `PARAGON FISKALNY`, Uber or airline email, a browser screenshot of an invoice |
| `CARD SLIP` | A payment terminal slip (PolCard, Verifone). Same amount and currency as its receipt |
| `AMEX` | American Express app transaction screen |
| `STATEMENT` | Any other banking app screen (Revolut, Monzo, a bank statement crop) |
| duplicate | The same receipt scanned twice. Drop it |

**Deduplicate** on merchant plus amount plus timestamp, keeping the earlier scan.
Receipts routinely get rescanned in a later batch.

**Group into claim lines.** One line per transaction. Match card evidence to a
receipt on **amount and date**, never on the card descriptor:
`PeP*CAFE~T2~AIRSIDE` is an airport breakfast and `UBER TRIP HTTPS://HELP.UB`
is a taxi. A card charge with no receipt (a TfL daily travel charge) is still a
line, with the receipt fields left null.

## Amounts

- **Card evidence exists** → `card_gbp` is the GBP figure read verbatim off the
  card screen. Never compute it from the printed exchange rate; the rate does not
  reliably reproduce the charge. 853.88 PLN can land as £175.31, an effective
  rate of 4.871 where 5.01 was quoted elsewhere the same day.
- **The GBP charge already includes the non-sterling transaction fee**, and that
  fee is claimed. Confirmed by the user.
- **No card evidence** → the claim stays in the receipt currency. Never invent an
  FX rate. PeopleSoft converts.
- **Split or part-paid bill** → claim the amount in the payment block at the foot
  of the receipt, not the headline total. `Total £103.21 ... Amount £51.61` is a
  £51.61 claim. Note it in the description so the approver does not query it.
- **Service charge and tip** printed on the bill are part of the claim.

## Fields

- `merchant` is the trading name on the receipt, not the card descriptor. Tube
  charges go in as `TFL Travel Charge`, the user's own convention.
- `description` is terse: `Dinner`, `Drinks`, `Lunch`, `Breakfast`, `Snack`,
  `Tube Travel`, `In-flight WiFi`. Infer it from the line items and the time of
  day, not from the merchant name. Add ` - context` only where the approver needs
  it, as in `Taxi - airport to hotel` or a split bill.
- `time` is the printed receipt timestamp, `HH:MM`, and is documentation only.
  **Order within a date is whatever order you write into `claim.json`.** The
  script sorts by date alone and is stable. Put an untimed daily travel charge
  where it actually happened: tube out at the start of the departure day, tube
  home at the end of the return day.

Write `claim.json` to the output folder. Schema and a worked example sit at the
top of `scripts/build_claim.py`.

## Build

```bash
python scripts/build_claim.py <claim.json> <input_dir> <output_dir>
```

Produces `Expenses.xlsx` and `Consolidated Expenses.pdf`, and prints the line
count, page count and per-currency totals. It performs no judgement: it does not
compute or convert amounts. If a number is wrong, fix `claim.json` and rerun.

`Expenses.xlsx`: sheet `Expenses`, ten columns, header filled `#1F3864` white
bold, panes frozen at A2, real dates as `DD/MM/YYYY`, money as `#,##0.00`, totals
as `SUMIF` on Claim Ccy, with one total row per currency actually claimed (GBP
then EUR first, then the rest sorted).

`Consolidated Expenses.pdf`: one source page per PDF page, in claim line order,
receipt pages before card evidence within a line. Navy `#1F3864` band top-left
carrying the line number in Helvetica-Bold 11 then
`{TYPE} - {Merchant} ({CCY} {amount})` in Helvetica 8, white. The amount shown is
whatever is on that page in that page's own currency. The line number repeats on
every page of a multi-page line. Source PDF pages are copied verbatim; images are
capped at 2000 px high and placed at 150 dpi.

## Size check

The consolidated PDF has to stay attachable, so keep it **under 9.5 MB**. Check
every freshly built one:

```bash
python scripts/compress_pdf.py "<output_dir>/Consolidated Expenses.pdf"
```

Under 9.5 MB it prints `under budget, left untouched` and changes nothing. Over,
it re-encodes the embedded JPEGs, replaces the file in place, and prints both the
setting it used and where it kept the untouched original. `--target-mb` moves the
budget when a specific limit is in play; `--dry-run` reports the setting without
writing.

The ladder exists to protect the numbers on a receipt, and reading those depends
on resolution first and JPEG quality second. So it walks quality down from 92 to
78 at **native resolution**, giving up no pixels at all, before it considers
resampling; only then does it cap effective dpi from 240 down to 150 holding
quality at 85; and it fails loudly rather than ship an illegible claim. Page
geometry, image count and the text layer are verified against the original before
anything is replaced.

Two rules that matter more than the setting:

- **Never run it twice on the same file.** Compressing an already compressed PDF
  stacks generation loss for almost no size gain. If a smaller file is wanted,
  rebuild from `claim.json` and compress the fresh one once, to the new target.
- **Never quietly shrink a file that fits.** The stated budget is the only reason
  to touch it.

Measured on a 53-page batch (14.18 MB, scans at 150 to 257 effective dpi):
native q80 gave 9.73 MB and native q78 gave 9.40 MB, both with every pixel
intact. An SSIM sweep against the source pixels put every rung within
0.003 of the others, so the target decides the outcome, not the rung.

## The two columns the user fills

`Expenses.xlsx` carries two cream-filled columns that are theirs to complete:

- **Expense Type** (K), a dropdown of all twenty codes as `CODE - Label`,
  prefilled with the default mapping below. The user overrides the food and
  drink lines to `CLENT` or `STFENT` here.
- **Attendees** (L), free text, client and colleague names. Both columns carry
  a tooltip and a header note showing the format, so the sheet explains itself
  to anyone who opens it.

**Never open PeopleSoft until both columns are filled and read back.** Stage 2
starts from the codes in the spreadsheet, never from the default mapping and
never from a question in chat.

```bash
python scripts/read_types.py "<output_dir>/Expenses.xlsx" <claim.json>
```

It prints line number, date, merchant, amount, the CODE for `EXPENSE_TYPE$N`
and the attendee cell verbatim, and folds both columns back into `claim.json` so
a rebuild keeps them. It errors on a blank or unrecognised type, and on an
entertaining line with no attendee, since PeopleSoft will refuse to save that.

**Read the attendee text, do not parse it.** The cell is prose a person wrote.
Turning `John Doe (Hillwood)` into the `Surname,Firstname` plus company
PeopleSoft wants is a reading job: names carry middle initials, particles,
double-barrels and inconsistent separators, and a parser that guesses wrong
files a real person's name incorrectly. The deterministic scripts exist to
protect the **money**, where a wrong value is silent and untraceable. Names are
not that.

**Default type mapping.** Use the obvious code where the receipt states plainly
what the spend was.

| Spend | Code |
|---|---|
| Taxi, ride-hailing | `TAXI` |
| Trains, metro, buses, transit passes | `PUBTRN` |
| Car hire | `RENTCAR` |
| Fuel for a hire car | `CARFUEL` |
| Road tolls, vignettes, congestion charge | `TOLLCNG` |
| Parking | `PARKING` |
| Hotel, and hotel city tax | `HOTEL` |
| In-flight WiFi | `OTHER` |
| **Food and drink, and anything not listed above** | `SUBSIST` |

Prefill food and drink as `SUBSIST`. Whether a given meal is really Client
Entertaining or Staff Entertaining turns on who was at the table, which no rule
can infer, so it is their call in column K. Never pre-empt it, and never widen
this table to cover it.

Attendee names reach the spreadsheet and this session by design. Do not treat
them as something to keep out of the transcript.

> ### STOP 1
> Report the totals, line count, page count and the PDF size. Show the user the
> two files and **wait**. They approve the numbers and fill columns K and L. Do
> not open a browser.

---

# Stage 2: file the lines

Full field map, action IDs and gotchas are in `reference/peoplesoft.md`. Read it
before starting. The shape of it:

1. Open the entry point and click `Add` with the prefilled Empl ID.
   If SSO has expired the page shows a two-digit number under "Approve sign in
   request". **Give the user that number and wait.** Never attempt MFA yourself.
2. Set Business Purpose `CLBUS`, Report Description, Default Location
   `United Kingdom`.
3. Fill line 0, including Billing Type `NRP`. It carries forward to every later
   line, so set it once only.
4. **Save for Later**, clear the attendee modal it raises, then read the Report
   ID off the page.
5. One line per save for the rest: Insert Line, poll for `TRANS_DATE$<n>`, fill,
   Save, clear the attendee modal, verify the amount reads back.
6. Read every row back. Check the line count and the total against the
   spreadsheet.

**One line per save is not negotiable.** Insert Line silently no-ops against an
uncommitted row, so filling nine rows and saving once loses eight of them.
`Totals (N Lines)` is the server-side committed count and the only honest
progress signal. About 14 seconds a line; three lines per browser call is safe.

**Every `CLENT` and `STFENT` line blocks the save until it has an attendee.** The
modal is a separate iframe. Row `$0` is prefilled with the user; add row `$1` and
put the guest in as `Surname,Firstname` plus company.

**The postback skip trick** keeps this as fast as it can be. Text fields only
call `addchg_win0()`, a local dirty flag with no server round trip. Only the two
dropdowns and Insert Line call `submitAction_win0()`. Set a dropdown's `.value`
and call `addchg_win0(el)` without the submit: the value still posts on the next
save.

**Dates are MM/DD/YYYY.** Typing UK order throws a validation dialog.

> ### STOP 2
> Report the Report ID, the line count, the total and the per-line table. Hand
> back. The user attaches the receipts and submits.
> **Never fire Summary and Submit.**

---

# If the user changes an expense type in the browser

Editing `EXPENSE_TYPE$N` after a line is saved blanks that line's `MERCHANT$N`.
Setting the type on the first pass does not, so this is a contingency, not a
routine step. If they do change one and ask you to tidy up:

1. Read the current state of every row.
2. Match each row against the spreadsheet on **date plus amount**, not row
   index, so inserts and reordering cannot misalign the restore. Check for
   ambiguous keys and unmatched rows first, and stop and ask if any turn up.
3. Write **only to cells that are actually empty**. A non-empty cell is a
   deliberate edit; never overwrite one.
4. Restore Merchant only. Leave types, descriptions and amounts as they left them.
5. Save, then confirm zero blanks, the line count and the total.

---

# After submission: the approval email

When the user asks for the email to their manager, follow
`reference/approval-email.md`. It is their own voice, captured verbatim, and it is
shorter and barer than a helpful draft wants to be. Under 100 words: the ask,
the total, the two largest items in the currency they are claimed in, one
sweep-up line, sign off. No report ID, no line count, no coding, no analysis, no
caveats about conversion. Write the draft into chat; never send it.

---

## House rules

- Never invent a number. Every amount traces to a page you read.
- Report totals and page counts plainly. If something did not reconcile, say
  which line and by how much.
- Expense type overrides and attendees are always the user's own call, made in
  the spreadsheet. On one 13-line batch those choices diverged from the default
  mapping on 5 lines, in ways no rule could infer.
