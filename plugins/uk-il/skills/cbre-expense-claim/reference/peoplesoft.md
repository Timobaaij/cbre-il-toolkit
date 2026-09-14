# PeopleSoft expense report playbook

Verified end to end on reports `0005236081` (13 lines, £383.64) and
`0005263886` (9 lines, £252.05).

Entry point:

```
https://myhcm.cbre.com/psp/hcmprd/EMPLOYEE/ERP/c/ADMINISTER_EXPENSE_FUNCTIONS.TE_EXPENSE_SHEET.GBL
```

Login is Microsoft SSO with MFA. The Playwright Chrome profile at
`%USERPROFILE%\.playwright-chrome-profile` caches the session, but it does
expire. When it does, the page shows "Approve sign in request" with a two-digit
number: give that number to the user and wait. Never attempt MFA yourself.

## Page structure

Everything lives in an iframe on the same origin, so `contentDocument` is
reachable. Find it by probing for a known field:

```js
const fr = [...document.querySelectorAll('iframe')]
  .find(x => { try { return x.contentDocument.getElementById('TRANS_DATE$0'); } catch (e) { return false; } });
```

Re-fetch the frame after every postback. The iframe document is replaced, so a
cached reference goes stale.

## The postback rule

This is the thing that makes bulk filling possible. Check the `onchange`
attribute to know which kind of field you have:

| Handler | Meaning |
|---|---|
| `addchg_win0(this); oChange_win0=this;` | Local dirty flag only. **No server round trip.** |
| `submitAction_win0(this.form, this.id)` | **Full postback.** DOM is rebuilt. |

Text fields (`TRANS_DATE`, `DESCR`, `TRANS_AMT1`, `MERCHANT`) are the first kind.
The two dropdowns (`EXPENSE_TYPE`, `EX_SHEET_LINE_BILL_CODE_EX`) and Insert Line
are the second.

**The skip trick:** set a dropdown's `.value` and call `addchg_win0(el)` without
calling `submitAction_win0`. The value is included in the next real form post and
survives the save. Verified: `EXPENSE_TYPE` set this way persisted through Save
for Later. This turns 3 postbacks per line into 1.

```js
const set = (id, val) => {
  const el = d.getElementById(id);
  if (!el) return false;
  el.value = val;
  try { w.addchg_win0(el); } catch (e) {}
  try { w.oChange_win0 = el; } catch (e) {}
  return true;
};
```

The only postback you cannot avoid is Insert Line, one per row. After firing it,
poll for `TRANS_DATE$<n>` to appear rather than sleeping a fixed time.

## Field map

Header:

| Field | ID | Value used |
|---|---|---|
| Empl ID | `PTS_CFG_CL_WRK_PTS_ADD_BTN` is the Add button | prefilled from the signed-in user - take it as it stands, never type or hard-code one |
| Business Purpose | `EX_SHEET_HDR_BUSINESS_PURPOSE` | `CLBUS` = Client/Business Meeting |
| Report Description | `EX_SHEET_HDR_SHEET_NAME` | free text, e.g. `Client Meeting Poland` |
| Default Location | `EX_LOCATION_VW2_DESCR` | type `United Kingdom`, pick `GBR01` from the autocomplete |

Per line, `$N` is the zero-based row index:

| Field | ID |
|---|---|
| Date | `TRANS_DATE$N` |
| Expense Type | `EXPENSE_TYPE$N` |
| Description | `DESCR$N` (textarea) |
| Billing Type | `EX_SHEET_LINE_BILL_CODE_EX$N` |
| Amount | `TRANS_AMT1$N` |
| Merchant | `MERCHANT$N` |
| Insert Line | `EX_LINE_WRK_EX_INSERT_LNPB$N`, fire via `submitAction_win0` |
| Delete Line | `EX_LINE_WRK_EX_DELETE_LNPB$N` |
| Line attachment | `ATTACHMENT_PB$N` |

Toolbar, all fired through `submitAction_win0(w.document.win0, '<id>')`:

| Action | Action ID |
|---|---|
| Save for Later | `#ICSetFieldEX_SHEET_ENTRY.EOTL_UI_BTN_ID.ER_TOOLBAR#SAVE` |
| Summary and Submit | `#ICSetFieldEX_SHEET_ENTRY.EOTL_UI_BTN_ID.ER_TOOLBAR#SUMMARYSUBMIT` |
| Attachments | `EX_HDR_WRK_ATTACHMENTS_PB` |
| myReceipts | `CB_EX_MYRCPT_WR_ATTACHMENTS_PB` |

## Gotchas

- **Dates are MM/DD/YYYY**, not UK order. Typing `24/07/2026` throws a validation
  dialog; dismiss it with the top-frame `#ICOK` button and retype `07/24/2026`.
  Always format dates as `%m/%d/%Y`.
- **Billing Type carries forward.** Set `EX_SHEET_LINE_BILL_CODE_EX$0` to `NRP`
  once on the first line; every later line inherits it. Do not set it per line.
- Amounts go in as the **claim amount in GBP**, matching the Claim Amount column.
- The calendar prompt (`TRANS_DATE$prompt$img$N`) sets the field without firing a
  `change` event. Type dates instead of using the picker.

## Expense type codes

`SUBSIST` Subsistence, `PUBTRN` Public Transportation, `TAXI` Taxi,
`PARKING` Parking, `HOTEL` Hotel, `AIRFARE` Airfare, `AIRFDOM` Airfare Domestic,
`CLENT` Client Entertaining, `STFENT` Staff Entertaining, `WRKLNCH` Working
Lunches, `TOLLCNG` Tolls/Congestion Charge, `PHONECM` Phone/Comms,
`RENTCAR` Car Rental, `CARFUEL` Car Rental Fuel, `POSTAGE` Courier/Postage,
`CONFSEM` Conferences/Seminars, `MBRSHIP` Membership/Subscriptions,
`ITEQUIP` IT Equipment, `LEGALPR` Legal & Professional Fees, `OTHER` Other.

Codes come from column K of `Expenses.xlsx`, never from a guess here. The
default mapping that prefills that column is in `SKILL.md`; whether a meal is
Subsistence, Client Entertaining or Staff Entertaining is his call alone.

Billing types: `NRP` Non - Reimbursable Producer (the default),
`BP` Billable Producer, `NRNP` Non - Reimburse Non Prod.

## One line per save

Fill and save **one line at a time**. Insert Line silently no-ops against an
uncommitted row: no error, no new row, nothing in the console. Filling every row
and saving once loses all but the first.

```
per line:  Insert Line on the last row
        -> poll for TRANS_DATE$<next>
        -> fill date, type, descr, amount, merchant
        -> Save for Later
        -> attendee modal appears: add row, fill, OK
        -> settle ~2s, verify TRANS_AMT1$<next> reads back
```

About 14 seconds a line. Three lines per `browser_evaluate` call is safe;
abort inside the loop the moment a read-back does not match.

`Totals (N Lines)` is the **server-side committed count** and the only honest
progress signal. The field values are client-side and will happily show nine
filled rows when one is saved.

### If a save goes wrong the whole form resets

A save that fails validation can drop you back to a blank **Create Expense
Report** with every unsaved line gone. The report itself survives with whatever
had already committed. Recover, do not retype into the blank form:

1. Go to the entry point, click `PTS_CFG_CL_WRK_PTS_PAGE_TOGGLE`
   ("Find an Existing Value").
2. Put the id in `EX_HDR_SRCH_VW_SHEET_ID`, then **dispatch `input` and
   `change`** on it.
3. Click `PTS_CFG_CL_WRK_PTS_SRCH_BTN`. Clicking `#ICSearch` does nothing.

### Modal frame ids increment

The attendee modal is **not** always `ptModFrame_0`. Each one gets a fresh id
(`_3`, `_9`, ...). Always resolve it live:

```js
const modal = () => [...document.querySelectorAll('iframe[id^="ptModFrame_"]')]
  .filter(f => f.offsetParent).pop() || null;
```

Its `contentDocument` throws while loading. Wrap every access in try/catch and
poll for `EX_SHEET_ATT_NAME$0` before touching it.

### Two traps in the row controls

- `EX_LINE_WRK_PB_ATTENDEES$N` (the per-line attendee icon) only renders
  **server-side**. A row you just typed into has no icon, so you cannot open its
  attendees directly. Let the save gate raise the modal instead.
- Do **not** re-fire Insert Line after handling a modal. It creates spare blank
  rows that then have to be found and filled or deleted.

## The attendees modal

**Save is blocked** while any `CLENT` or `STFENT` line has no attendees:

> Attendees are required for the Staff Entertaining expense on line 1.

Because types are set on the first pass, this gate fires on the very first Save
for Later, and on every save that commits an entertaining line. Plan for it.

The modal is **a separate iframe** from the main `ptifrmtgtframe`, with its own
`document.win0` and its own `submitAction_win0`. Its id is not fixed: resolve it
live (see below).

| Thing | ID |
|---|---|
| Modal iframe | `ptModFrame_0` |
| Name | `EX_SHEET_ATT_NAME$N` |
| Company | `EX_SHEET_ATT_ATTENDEE_COMPANY$N` |
| Title | `EX_SHEET_ATT_TITLE$N`, optional, not starred |
| Add a row | `EX_SHEET_ATT$new$0$$0`, `submitAction_win0`, postback inside the modal |
| Delete a row | `EX_SHEET_ATT$delete$0$$0` |
| OK | `PSFT_CLOSE_MODAL$0`, plain `.click()` |
| Cancel | `#ICCancel` |

- Row `$0` comes **prefilled** with `Baaij,Timo` / `CBRE Ltd.`. Leave it and add
  the guest as row `$1`.
- Name format is `Surname,Firstname`. The field has a lookup prompt
  (`EX_SHEET_ATT_NAME$prompt$N`) but free text posts fine, which is what
  external client names need.
- Adding a row is instant. Closing with OK takes about 5 seconds; poll for
  `ptModFrame_0` losing `offsetParent` rather than sleeping.
- After OK the line total flips from `Totals (0 Lines)` to `Totals (1 Line)`,
  which is the signal the line was accepted.

### Two false alarms, do not repeat them

- **`Processing Please wait` is always in the DOM.** It is a hidden overlay, not
  a live state. Testing for it in a poll loop hangs forever. Test for real
  content instead.
- **`Totals (0 Lines)` before the first successful save is not an error.** The
  fields hold your values client-side; the count only updates server-side.

The report number is not labelled `Report ID` in the page text. Match a bare
10-digit number: `/\d{10}/`.

## Order of operations

1. Open the entry point, click `Add` with the prefilled Empl ID.
2. Set Business Purpose, Report Description, Default Location.
3. Fill line 0, including Billing Type `NRP`.
4. **Save for Later** to mint the Report ID, then read it off the page.
5. For each remaining line: Insert Line, poll for the row, fill it via the skip
   trick, Save, clear the attendee modal, verify the amount reads back.
6. Read back every row and check the line count and total against the
   spreadsheet before telling the user it is done.
7. Hand over. He attaches the receipts.
8. **Stop there.** Summary and Submit sends the report for approval. Never fire
   it without the user explicitly asking in this session.

## Never automated

**Summary and Submit**, and attaching receipts. Both are his.

Expense types and attendees are his judgement, made in columns K and L of
`Expenses.xlsx` before PeopleSoft is opened. Type in what those columns say;
never substitute your own reading.

### Changing an expense type blanks the Merchant

Editing `EXPENSE_TYPE$N` on a saved line clears `MERCHANT$N`. Setting the type
on the first pass does not, so this only bites when he edits a type in the
browser afterwards. The refill procedure is in `SKILL.md`; the rule that matters
is to write only to cells that are actually empty, matching rows on date plus
amount rather than row index.

## Recording a session

To relearn the form after a PeopleSoft upgrade, inject a listener into every
frame that logs `click` and `change` with element IDs into `localStorage` under
`__ps_rec`, plus a `setInterval` on the top document that re-attaches to the
iframe after each postback. Read it back with a `browser_evaluate` that parses
that key.
