# Browser setup

The generated tool needs one change to your browser, and a wrong setting here is the single most
common reason a run produces no files at all — silently, across every brochure.

## Why it is needed

By default Chrome and Edge **open** a PDF in their built-in viewer rather than saving it. That is
fine when a server asks for a download, but none of the brochure hosts measured for this tool send
`Content-Disposition: attachment`. Without the change, every brochure opens in the viewer and nothing
reaches your Downloads folder.

The setting applies to **top-level navigations only**, which is why the tool opens each brochure in a
window rather than a hidden frame. The built-in PDF viewer always claims a PDF loaded into a
sub-frame, and this setting cannot override that.

## Two ways to run step 2

A browser tab is allowed one download. Anything after that in the same tab is blocked — or worse,
silently opened in the viewer with no prompt at all. So the tool never reuses a window: each brochure
gets its own, which closes itself once the download is under way. Closing one early is harmless,
because the browser owns a download once it has started.

That leaves a choice, and either route ends at the same zip:

- **Save next brochure** — one click per file. Each click is a user gesture, which browsers permit
  unconditionally, so this needs **no permission of any kind** and cannot be blocked. The button
  advances by itself, so you can keep pressing the same button.
- **Start automated run** — one press for all of them. Because only the first window comes from your
  click, the browser must be allowed to open popups for the page. If popups are blocked, the run
  stops immediately and tells you, then you allow them and press Start again. Files already sent are
  skipped.

## Chrome

1. Paste `chrome://settings/content/pdfDocuments` into the address bar and press Enter.
2. Select **Download PDFs**.

## Edge

1. Paste `edge://settings/content/pdfDocuments` into the address bar and press Enter.
2. Turn **Always download PDF files** on.

Change it back afterwards if you prefer reading PDFs in the browser. The setting has no other effect
on the tool.

## The multiple-downloads prompt

The first time the tool triggers several downloads, the browser asks whether the page may download
multiple files. Allow it. If you dismiss it, only the first file arrives — click the icon at the
right-hand end of the address bar to allow it, then press **Start downloading** again. Files already
collected in step 3 are skipped, so re-running is safe.

## Confirm before committing

Step 1 of the tool has a **Test with one brochure** button. Use it, and read the result:

- **The window stays blank and a PDF appears in your Downloads folder** — the setting is applied, and
  the rest of the run will behave.
- **The brochure appears on screen in the window** — the setting has not taken effect. Re-apply it,
  reload the tool, and test again.

This turns a silent 22-file failure into a one-file check you can actually read.

## If the setting cannot be changed

On a managed device the PDF setting is occasionally locked by policy. In that case the tool's
automated step will not save files, and the fallback is manual:

1. Skip step 2.
2. Open each link from the table (they are all listed with their properties), and save each PDF from
   the browser's viewer with `Ctrl+S`.
3. Drag everything you saved onto step 3 as normal — renaming, validation and zipping all still work,
   because that half of the tool reads local files and needs nothing from the browser.

The result is identical; only the fetching is manual.

## What the tool never does

It does not change any browser setting itself, and it cannot — a page has no such access. Every
change above is one you make yourself, and it is reversible.
