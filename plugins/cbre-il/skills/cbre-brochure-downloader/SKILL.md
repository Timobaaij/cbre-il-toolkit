---
name: cbre-brochure-downloader
description: Download every brochure PDF linked from a property longlist spreadsheet and package them as one clean zip, ready for cbre-property-longlist. Reads the longlist's hidden Excel hyperlinks, then generates a self-contained HTML tool the user opens in Chrome or Edge to do the actual downloading, because the sandbox has no internet access but their browser does. Renames each PDF after its property, validates every file is a real PDF, deduplicates shared links, and flags anything that is not a direct PDF instead of guessing. Use whenever the user wants to download the brochures from a longlist, grab or fetch the PDFs from an availability sheet, get all the brochures for a requirement, or turn a longlist's brochure column into a folder of files. Trigger even when the need is only described (I need all the brochures off this sheet; pull the PDFs from this availability list).
---

# Brochure Downloader

Turns the brochure links in a property longlist into **one zip of correctly named PDFs**, which is
the input `cbre-property-longlist` expects.

## Why it works this way (read once)

This sandbox has **no outbound network access**. Python here cannot fetch a single PDF. The user's
own browser, outside the sandbox, is the only thing on the path with real internet access — so this
skill does not download anything. It **generates a tool** that the user's browser runs.

Two browser facts drive the whole design, both measured rather than assumed:

- Most brochure hosts send no `Access-Control-Allow-Origin`, so a page **cannot `fetch()`** these
  PDFs into JavaScript. An in-browser zip built by fetching is impossible.
- Almost no host sends `Content-Disposition: attachment`, so navigating to a PDF **opens the
  viewer** instead of saving, unless the browser's PDF setting is changed.

So the bytes travel: **internet → browser navigation (no CORS) → Downloads folder → dragged back
onto the page (no CORS) → renamed, validated, zipped.** A navigation gets bytes onto disk; a dropped
local file is readable by JavaScript. Neither half alone works.

**One fresh top-level window per file, never reused.** A browser tab is allowed exactly one download;
what happens to the second varies and is never obvious. Three mechanisms failed here before the cause
was understood, each in a different way:

1. **Hidden iframe** — the built-in PDF viewer claims any PDF loaded into a sub-frame, so the
   brochure rendered invisibly and nothing was saved. The "Download PDFs" setting cannot help,
   because it governs top-level navigations only.
2. **One reused window, fire-and-forget** — the multiple-downloads prompt blocked files 2..n while
   the loop raced past them. Only the first arrived.
3. **One reused window, pausing for that prompt** — the second file silently degraded to *rendering*
   in the viewer, with no prompt shown at all.

The allowance is per tab, so a fresh window per file gets a fresh allowance. Its single failure mode,
a blocked popup, is **detectable** (`window.open` returns null) — unlike a gated download, which
fails invisibly. Do not consolidate these back into one window; `TestDownloadMechanism` guards it.

## The loop

**Toolkit update check (run once, first).** Run `python helpers/version_check.py`. It prints a one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise it is silent); it does nothing but a single public version lookup, never blocks the run, and is safe to ignore.


1. **Build the tool.** One command, no network, no third-party packages:

   ```
   python helpers/build.py --xlsx "<longlist.xlsx>" --out "<output dir>" [--client "Name"] [--sheet "Longlist"]
   ```

   It prints the detected columns and the counts. Read them — that is your report to the user.
   Exit codes: `0` fine, `2` file or sheet unreadable, `3` no brochure column found (the message
   names the headers it did see; ask the user which column holds the brochures and pass `--sheet`
   or fix the sheet).

2. **Deliver both output files to the user**: `brochure-downloader.html` and `gaps.md`.

3. **Tell them the three steps**, briefly and in this order — the first one is not optional and
   the run silently produces nothing without it:
   - Set the browser to download PDFs rather than open them
     (`chrome://settings/content/pdfDocuments` → **Download PDFs**; Edge:
     `edge://settings/content/pdfDocuments` → **Always download PDF files**). The tool's step 1 has
     a one-brochure test button, and tells them how to read the result: the window staying blank means
     the setting is applied; the brochure appearing on screen means it is not.
   - Step 2 offers two routes, and they should pick one:
     **Save next brochure** — one click per file, needs no permission, always works; or
     **Start automated run** — one press for all of them, but the browser must be allowed to open
     popups for the page. If popups are blocked the run stops and says so.
   - Then drag the downloaded files back onto step 3.
   - Download `brochures_<client>.zip` and upload it back here.

4. **Report honestly** what the build found: how many properties, how many distinct files, and
   anything flagged. Do not describe the run as complete — you cannot see whether it worked. The
   user's zip and its `_gaps.md` are the evidence.

## What the build decides, and what it refuses to decide

- **Finds the brochure column** by header name (`Brochure`, `Brochure Link`, `PDF`, `Particulars`…),
  falling back to hyperlink density. The fallback excludes map links, because a longlist's `Map`
  column is full of hyperlinks and would otherwise win.
- **Reads Excel hyperlinks**, since the visible cell text is usually just the word "Brochure" and
  the URL is invisible in the sheet. Also handles `=HYPERLINK("…")` formulas.
- **Names each file** `NN_Property_Town.pdf`, numbered from the sheet's own No. column so the folder
  sorts in longlist order. That filename becomes provenance in the downstream Source Ledger, which
  is why it carries the property identity rather than the host's hash.
- **Deduplicates** rows pointing at the same URL into one download named `NN+NN_…`, so the sharing
  is visible in the filename itself.
- **Refuses to guess** on a link that is not clearly a PDF. A URL with no extension is treated as a
  file only when its last path segment is an opaque identifier (a GUID or hex hash — how Azure blob
  storage serves PDFs); a human-readable slug is treated as a page and **flagged** for the user with
  its link. Downloading a landing page as though it were a brochure would put an HTML file into the
  set the downstream skill treats as source evidence.
- **Records rows with no link** in `gaps.md` rather than dropping them.

## Honest limitations — state these, do not paper over them

- **The tool cannot confirm a download succeeded.** Cross-origin navigation downloads fire no
  JavaScript event. Step 2 reports *triggered*, never *complete*. Step 3 is the verification: it
  checks each file's `%PDF-` magic bytes and lists whatever is missing.
- **Chromium only.** The design depends on the Chrome/Edge PDF-download setting.
- **Login-gated portals will not work.** If a link needs a signed-in session, the download lands as
  an HTML login page; step 3 rejects it as not-a-PDF and lists it as missing.
- The one-brochure test exists because a wrong setting fails *silently across every file*. Do not
  suggest skipping it.

## Handing the zip to cbre-property-longlist

The zip unpacks to the PDFs plus `_manifest.json` (file → property → source URL, the traceability
record), `_gaps.md` and `_README.md`. Metadata files are deliberately `.json`/`.md` and never
`.csv`/`.xlsx`, because that skill treats spreadsheet inputs as "trackers" needing an interpretation
round — a stray `manifest.csv` in the inputs folder would trigger spurious work.

Tell the user to add the **original longlist spreadsheet** to the same folder; that skill wants the
availability sheet alongside the brochures.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Test opens the brochure on screen instead of saving it | The PDF setting has not taken effect. Re-apply it, reload the tool, test again. This is the expected visible signal, not a bug. |
| Nothing happens at all on test | The popup was blocked. Allow popups for the page (address-bar icon), then test again. |
| Automated run stops early saying popups blocked | Expected and detected, not a silent failure. Allow popups for the page and press Start again, or use **Save next brochure** instead. |
| Only the first file downloads | A symptom of reusing one tab, which this version no longer does. If it reappears, the download trigger has been changed back — check `TestDownloadMechanism`. |
| A file is "not a PDF" | The server returned a page — often a login wall or an expired link. Open the link from the attention panel and save the brochure by hand. |
| Files land as "unrecognised" | Filename tolerance did not reach; assign them with the dropdown in step 3. |
| Zip button disabled | Nothing collected yet. Drag files onto step 3 first. |
| `exit 3` from build.py | No brochure column. The error names the headers found; confirm which column holds the links. |

## Layout

```
helpers/build.py         entry point: spreadsheet -> tool + gaps.md
helpers/xlsx_links.py    stdlib-only xlsx reader (cells + hyperlinks)
helpers/longlist.py      column detection, dedupe, classification, filenames
helpers/render.py        payload injection
templates/tool.html      the generated tool (self-contained, no CDN)
reference/browser-setup.md   the browser change, with fallbacks
tests/                   pytest suite, runs offline
```

Nothing outside the standard library, on either side. The page bundles no zip library — it writes a
store-only archive itself, which costs nothing in size because PDFs are already compressed.
