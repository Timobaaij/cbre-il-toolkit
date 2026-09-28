# PeopleSoft expense report playbook

Verified end to end on four live reports: 13 lines; 9 lines; 28 lines, filed
for a second employee with both files attached; and 20 lines (13 GBP + 7 EUR,
2 attendee lines, both files attached), about 10 minutes from MFA to
hand-back using the job template below.

Entry point:

```
https://myhcm.cbre.com/psp/hcmprd/EMPLOYEE/ERP/c/ADMINISTER_EXPENSE_FUNCTIONS.TE_EXPENSE_SHEET.GBL
```

Login is Microsoft SSO with MFA. The Playwright Chrome profile at
`%USERPROFILE%\.playwright-chrome-profile` caches the session, but it does
expire. When it does, the page shows "Approve sign in request" with a two-digit
number: give that number to the user and wait. Never attempt MFA yourself.

## Filing for someone else

The Empl ID box (`EX_HDR_ADD_VW_EMPLID`) is prefilled with the signed-in user's
own id. To file a colleague's claim, **pick the id from the
lookup, do not type it**. Typing sets `class=PSERROR` and `Add` refuses.

```js
d.getElementById('EX_HDR_ADD_VW_EMPLID$prompt').click();   // opens ptModFrame_0
// then click the SEARCH_RESULT link whose text is the id
```

The lookup is backed by `EX_EE_AUTH_VW3`, the expense-user **authorisation**
view: it lists only employees this login may file for. If a colleague is absent
they have not authorised the user, and no amount of retrying will help.

A dying session also collapses that list to one row, so **a "1 of 1" result
right before a session drop is not proof of missing authorisation**. Re-login
and look again before telling the user they lack access.

Once the report opens, the header shows the employee's name, and attendee row
`$0` prefills with **that employee**, not the signed-in user.

Folder convention: a batch folder named `<Month Year> - <Name> - <Empl ID>`
carries the id to file under. Use it rather than the prefilled default.

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
| Report Description | `EX_SHEET_HDR_SHEET_NAME` | free text, **30 characters max** (silently truncated), e.g. `Client Mtgs CZ SK HU Aug 2026` |
| Default Location | `EX_LOCATION_VW2_DESCR` | see below: must be typed with real keystrokes |

**Default Location cannot be set by `.value`.** The field has no `onchange`
handler, and a scripted value or synthetic `input`/`keyup` never opens the
autocomplete. What works:

1. Make sure the field is empty (a failed attempt leaves text behind, and
   typing appends to it: `United KingdomUnited Kingdom`).
2. `browser_type` with `slowly: true`, target
   `iframe#ptifrmtgtframe >> internal:control=enter-frame >> #EX_LOCATION_VW2_DESCR`,
   text `United Kingdom`.
3. Snapshot the iframe body: a small table `Expense Location | Description`
   with `GBR01 | United Kingdom` appears at the top. `browser_click` the
   `United Kingdom` cell.

Every line's `EX_LOCATION_VW6_DESCR$N` then fills with `United Kingdom` on
save. Do not set it per line.

Per line, `$N` is the zero-based row index:

| Field | ID |
|---|---|
| Date | `TRANS_DATE$N` |
| Expense Type | `EXPENSE_TYPE$N` |
| Description | `DESCR$N` (textarea) |
| Billing Type | `EX_SHEET_LINE_BILL_CODE_EX$N` |
| Amount | `TRANS_AMT1$N` |
| Currency | `EX_SHEET_LINE_TXN_CURRENCY_CD$N` (text, `addchg` only, defaults `GBP`) |
| Merchant | `MERCHANT$N`, **40 characters max** (silently truncated) |
| Location | `EX_LOCATION_VW6_DESCR$N`, fills from the header Default Location on save |
| Payment Type | `PAYMENT_TYPE$N`, disabled, always `OOP` Out of Pocket |
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
- Amounts go in as the **Claim Amount in the Claim Ccy**, both straight from the
  spreadsheet. A EUR line is `TRANS_AMT1$N = 40.00` plus
  `EX_SHEET_LINE_TXN_CURRENCY_CD$N = EUR`, set with the skip trick like any text
  field; it posts on save and reads back as `EUR`. PeopleSoft converts, so the
  report total (`Totals (N Lines) x GBP`) will not equal the spreadsheet GBP
  total when non-GBP lines exist. Check it equals GBP total plus the converted
  foreign lines, i.e. it is larger than the GBP total and in a plausible range.
  **Set the currency on every line**, including `GBP`. Whether a new row
  inherits the row above's currency is untested; setting it every time makes
  that irrelevant.
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
Subsistence, Client Entertaining or Staff Entertaining is the user's call alone.

Billing types, verbatim from the dropdown: `NRP` Non - Reimbursable Producer
(the default and, per the user, always the answer), `BIP` Billable Producer,
`NNP` Non - Reimburse Non Prod.

Billing Type governs whether the cost is rebilled to a client. It is **not**
about whether the employee is repaid, so cash and personal-card lines still go
in as `NRP`. Do not raise this as a problem.

## Never block a browser_evaluate on a whole batch

A `browser_evaluate` that runs past the MCP request timeout is killed, and the
teardown navigates the page to `about:blank`, destroying the session. Batch size
is not the real variable: **wall-clock inside one call** is, and attendee rows
dominate it, since every added attendee row is its own postback. A batch of
three attendee-heavy lines is enough to hit it.

Two consequences:

- **The browser finishes the work anyway.** A timed-out batch still commits its
  lines. After any timeout or interrupt, **re-read the committed rows before
  concluding anything failed**, and never refile blind: doing so duplicates
  lines.
- **Recovery costs a fresh login.** `about:blank` means SSO, MFA, and reopening
  the report by id.

So run the filing as a **background job**: one short call starts an un-awaited
async loop that records progress on a global, and every later call is a
sub-second poll. No call is ever long enough to time out.

```js
window.__startJob = (LINES) => {
  const J = { total: LINES.length, done: [], current: null, running: true, error: null };
  window.__job = J;
  (async () => {                     // NOT awaited: the outer call returns at once
    try { /* insert, fill, save, clear modal, verify, per line */ }
    catch (e) { J.error = String(e); }
    finally { J.running = false; }
  })();
  return 'started ' + LINES.length;  // returns immediately
};
```

Poll with `() => ({ running: __job.running, done: __job.done.length, error: __job.error })`.
The whole remaining queue can go in one job. Measured on a 20-line report: about
10 s a plain line, about 20 s an attendee line, 19 lines in 6 minutes. Poll
with `browser_wait_for` `time: 45-60` between reads rather than many short
polls.

### Working job template (verified, 19 lines, zero failures)

`window.__job` lives on the **top** document, which never reloads: only the
`ptifrmtgtframe` iframe is replaced by postbacks. So the loop survives every
save. Line 0 is filled and saved by hand first (it mints the Report ID); the
job then does rows `1..N`. Each entry is
`[MM/DD/YYYY, CODE, descr, amount, ccy, merchant, [[Surname,Firstname, Company], ...]]`.

```js
() => {
const LINES = [ /* ["08/23/2026","SUBSIST","Dinner","43.99","GBP","U Mateje",[]], ... */ ];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const F=()=>{const f=document.querySelector('iframe#ptifrmtgtframe'); try{const d=f.contentDocument; return d&&d.body?{d,w:f.contentWindow}:null}catch(e){return null}};
const M=()=>{const f=[...document.querySelectorAll('iframe[id^="ptModFrame_"]')].filter(x=>x.offsetParent).pop(); if(!f) return null; try{const d=f.contentDocument; return d&&d.getElementById('EX_SHEET_ATT_NAME$0')?{d,w:f.contentWindow}:null}catch(e){return null}};
const tot=()=>{const x=F(); if(!x) return -1; const m=x.d.body.innerText.match(/Totals \((\d+) Lines?\)/); return m?+m[1]:-1};
const poll=async(fn,ms)=>{const t0=Date.now(); while(Date.now()-t0<ms){let v; try{v=fn()}catch(e){} if(v) return v; await sleep(300);} return null};
const J={total:LINES.length,done:[],current:null,running:true,error:null,log:[]}; window.__job=J;
(async()=>{ try{
 for(let i=0;i<LINES.length;i++){
  const n=i+1; const [dt,ty,de,am,cu,me,att]=LINES[i]; J.current=n;
  if(tot()!==n) throw 'line '+n+': expected '+n+' committed, got '+tot();
  let x=F(); x.w.submitAction_win0(x.w.document.win0,'EX_LINE_WRK_EX_INSERT_LNPB$'+(n-1));
  if(!await poll(()=>{const y=F(); return y&&y.d.getElementById('TRANS_DATE$'+n)&&y.d.getElementById('EXPENSE_TYPE$'+n)},30000)) throw 'row '+n+' never appeared';
  await sleep(500); x=F(); const d=x.d,w=x.w;
  const set=(id,v)=>{const el=d.getElementById(id); if(!el) throw id+' missing'; el.value=v; try{w.addchg_win0(el)}catch(e){} try{w.oChange_win0=el}catch(e){}};
  set('TRANS_DATE$'+n,dt); set('EXPENSE_TYPE$'+n,ty); set('DESCR$'+n,de); set('TRANS_AMT1$'+n,am); set('EX_SHEET_LINE_TXN_CURRENCY_CD$'+n,cu); set('MERCHANT$'+n,me);
  if(d.getElementById('EXPENSE_TYPE$'+n).value!==ty) throw 'type not set '+n;
  w.submitAction_win0(w.document.win0,'#ICSetFieldEX_SHEET_ENTRY.EOTL_UI_BTN_ID.ER_TOOLBAR#SAVE');
  const r=await poll(()=>M()?'modal':(tot()===n+1?'saved':null),60000);
  if(!r) throw 'line '+n+': no commit and no modal';
  if(r==='modal'){
   if(!att.length) throw 'line '+n+': unexpected attendee modal';
   for(let k=1;k<=att.length;k++){ const m=M(); m.w.submitAction_win0(m.w.document.win0,'EX_SHEET_ATT$new$0$$0');
     if(!await poll(()=>{const q=M(); return q&&q.d.getElementById('EX_SHEET_ATT_NAME$'+k)},20000)) throw 'att row '+k+' not added'; await sleep(400); }
   const m=M();                                  // add ALL rows first, then fill
   att.forEach(([nm,co],j)=>{const a=m.d.getElementById('EX_SHEET_ATT_NAME$'+(j+1)), b=m.d.getElementById('EX_SHEET_ATT_ATTENDEE_COMPANY$'+(j+1)); a.value=nm; b.value=co; try{m.w.addchg_win0(a); m.w.addchg_win0(b)}catch(e){}});
   const rb=att.map((_,j)=>[m.d.getElementById('EX_SHEET_ATT_NAME$'+(j+1)).value, m.d.getElementById('EX_SHEET_ATT_ATTENDEE_COMPANY$'+(j+1)).value]);
   J.log.push({n,att:rb,row0:m.d.getElementById('EX_SHEET_ATT_NAME$0').value});
   if(rb.some(([a,b])=>!a||!b)) throw 'blank attendee line '+n;
   m.d.getElementById('PSFT_CLOSE_MODAL$0').click();
   if(!await poll(()=>tot()===n+1&&!M(),60000)) throw 'line '+n+': not committed after attendees';
  } else if(att.length) throw 'line '+n+': saved without attendee modal';
  await sleep(1500); const y=F();
  const ra=y.d.getElementById('TRANS_AMT1$'+n).value, rc=y.d.getElementById('EX_SHEET_LINE_TXN_CURRENCY_CD$'+n).value;
  if(parseFloat(ra.replace(/,/g,''))!==parseFloat(am)||rc!==cu) throw 'line '+n+' readback '+ra+' '+rc;
  J.done.push(n);
 }
}catch(e){J.error=String(e)} finally{J.running=false} })();
return 'started '+LINES.length; }
```

Build `LINES` from the `read_types.py` output and `claim.json` (claim amount,
claim ccy, merchant, description), with the attendee cell **read** into
`[Surname,Firstname, Company]` pairs by you, not parsed. Surface `__job.log`
in the hand-back so the attendee names that went in are visible.

The final read-back loops `TRANS_DATE$n` while it exists and prints date,
type, amount, currency, merchant, billing and location for every row; compare
against the spreadsheet line by line.

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

**Save is blocked** while any `CLENT`, `STFENT` or **`WRKLNCH`** line has no
attendees:

> Attendees are required for the Staff Entertaining expense on line 1.
> Attendees are required for the Working Lunches expense on line 4.

`WRKLNCH` gates exactly like the other two, and its modal can be slow to render.
This is the trap: a poll that treats the **client-side** row as proof of a
commit breaks out before the modal appears, the attendees are never entered, and
the line is silently discarded on the next save with no error anywhere.
**Never treat a client-side field as evidence of a commit.** Poll only for the
modal or for `Totals (N Lines)`.

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

- Row `$0` comes **prefilled with the employee the report belongs to**, which is
  not necessarily the signed-in user. Leave it and add guests from row `$1`.
- **Add every row first, then fill them all.** Firing `EX_SHEET_ATT$new$0$$0`
  again posts back and **wipes a row you filled but have not yet posted**, so
  add-fill-add-fill leaves earlier rows blank, fails the save, and drops the
  whole expense line with no error. Add N rows, then write the N names and
  companies with no postback between the writes, then read them all back and
  abort on any blank before clicking OK.
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
7. **Attach both files and Save for Later** (see Attachments below).
8. Hand over.
9. **Stop there.** Summary and Submit sends the report for approval. Never fire
   it without the user explicitly asking in this session.

## Attachments

Every run ends here. Attach `Consolidated Expenses.pdf` and `Expenses.xlsx` to
the report, then Save for Later. Verified on a live report.

The dialog states its own rules, and they bite:

1. **Filenames: letters, numbers and underscore only.** `Consolidated
   Expenses.pdf` has a space. Upload a renamed copy, `Consolidated_Expenses.pdf`.
2. **Total of all attachments under 10 MB.** The PDF budget of 9.5 MB in
   `SKILL.md` exists for this; the Excel adds ~0.01 MB.
3. **Save for Later after uploading**, before any submit.

Flow, each file:

```
EX_HDR_WRK_ATTACHMENTS_PB          -> attachments list modal (ptModFrame_0)
ATT_PNLS_WRK_ATTACHADD             -> upload sub-modal (next ptModFrame_N)
click the input[type=file]         -> Playwright intercepts the chooser
browser_file_upload <path>         -> sets the file
click #Upload                      -> sub-modal closes, row appears in the list
... repeat for the second file ...
#ICSave on the list modal          -> OK
Save for Later on the toolbar
```

**Proof both survived:** after the final Save for Later the page turns into
**Modify Expense Report** and the header link `EX_HDR_WRK_ATTACHMENTS_PB`
reads `Attachments (2)`. That count is server-side, so read it instead of
reopening the list modal (which is slower and after the save did not render
for a scripted open).

```js
[...d.querySelectorAll('a')].find(a => a.id === 'EX_HDR_WRK_ATTACHMENTS_PB').innerText  // "Attachments (2)"
```

Mechanics that held on a live report:

- The list modal is `ptModFrame_2`, each upload sub-modal the next id (`_3`,
  `_4`). Resolve live; the list modal's OK is `#ICSave` inside it.
- Click the file input with `browser_click` on
  `iframe#ptModFrame_N >> internal:control=enter-frame >> input[type=file]`,
  then `browser_file_upload`, then click `#Upload` inside that sub-modal via
  `browser_evaluate`. The filename shows up in the list modal's text within a
  second or two; poll the list's `innerText` for it.
- A failed `browser_file_upload` (wrong root) leaves the chooser open, so the
  retry with the right path just works. Do not click the input again.

**Playwright only uploads from its allowed roots, and they change per
session.** Anything else fails with "outside allowed roots", the scratchpad
and the batch folder included. The error message lists the current roots
(seen: `...\<a working folder>\.playwright-mcp`, and a different folder in
the next session). Workflow:

1. Fire the upload once at any path; read the allowed roots off the error.
2. `Test-Path` the two target names in that root, then `Copy-Item` (never
   `Move-Item -Force`: the permission classifier blocks it as destructive)
   the files in under underscore names.
3. Upload, then `Remove-Item` exactly those two copies.

**The file-chooser trap.** Every click on a file input opens a chooser that
Playwright captures instead of the OS, so **the user sees nothing when they try
to attach by hand**, and repeated attempts queue up unanswered choosers. Once
queued they block every `browser_evaluate` with "does not handle the modal
state". Reloading does not clear them, and `browser_file_upload` with no paths
cancels only one per call. **Open a new tab and close the old one.** Better:
never leave a chooser unanswered, and never ask the user to click a file input
while Playwright is attached to the browser.

## Never automated

**Summary and Submit.** That one is the user's.

Attachments used to be the user's too. They are ours now: the chooser trap above
makes it impossible for them to do by hand while Playwright is driving.

Expense types and attendees are the user's judgement, made in columns K and L of
`Expenses.xlsx` before PeopleSoft is opened. Type in what those columns say;
never substitute your own reading.

### Changing an expense type blanks the Merchant

Editing `EXPENSE_TYPE$N` on a saved line clears `MERCHANT$N`. Setting the type
on the first pass does not, so this only bites when they edit a type in the
browser afterwards. The refill procedure is in `SKILL.md`; the rule that matters
is to write only to cells that are actually empty, matching rows on date plus
amount rather than row index.

## Recording a session

To relearn the form after a PeopleSoft upgrade, inject a listener into every
frame that logs `click` and `change` with element IDs into `localStorage` under
`__ps_rec`, plus a `setInterval` on the top document that re-attaches to the
iframe after each postback. Read it back with a `browser_evaluate` that parses
that key.
