# Kato Cowork Bridge

Lets a colleague run the Kato longlist from **Claude Cowork**, which has no Playwright, no shell MCP,
and no outbound network at all beyond WebSearch/WebFetch.

The Kato API cannot be reached from a sandbox, and no amount of cookie-copying changes that: there is
no socket. So the network boundary moves instead. A Chrome extension does all the network work inside
a browser that is **already signed in**, and writes one bundle file. Cowork receives the bundle and
runs the rest of the pipeline offline.

```
Chrome (signed in to Kato)                    Claude Cowork (sandboxed)
  extension  ──►  kato_bundle_<reqid>.zip  ──►  kato_ingest.py  ──►  stages 2-7 unchanged
```

No credential ever leaves the browser or reaches Claude.

---

## Part 1 - the extension

### Install (colleague, developer mode)

1. Copy the `extension/` folder somewhere permanent, e.g. `C:\Users\<you>\KatoCapture\`.
2. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick that folder.
3. Pin the green **K** icon to the toolbar.

If developer mode is blocked by CBRE policy, IT needs to deploy it instead: see *For IT* below.

### Use

1. Open the Kato requirement whose longlist you want, so the address contains `/requirements/<number>/`.
2. Click the **K** icon. A capture tab opens.
3. Choose whether to include brochures (needed for site plans; much bigger bundle).
4. Click **Capture and save bundle** and choose where to save.
5. Keep the tab open until it finishes. Progress and any failures are shown live.

**If it says it cannot reach the Kato tab**, reload the Kato page and click the icon again. That
happens when the extension was installed after the tab was already open.

### For IT

The extension reads only data the signed-in user can already see, and writes one local file.

| | |
| --- | --- |
| Permissions | none |
| Host permissions | `https://*.kato.app/*`, `https://as-images.imgix.net/*`, and two Kato asset buckets: `https://s3-eu-west-1.amazonaws.com/agents-society-assets/*` and `.../agents-society-assets-files/*` |
| Session cookie | **not readable** - it is `httpOnly`. Only `XSRF-TOKEN` is read, which is non-`httpOnly` by design so it can be echoed back as a header, exactly as the existing Python tool does |
| Remote code | none. MV3 forbids it and no third-party library is bundled: the ZIP writer is ~120 lines of our own code using the browser's built-in `CompressionStream` |
| Network destinations | Kato and its two media hosts only. Nothing is uploaded anywhere |
| Telemetry | none |
| `webRequest` / `cookies` / `tabs` | not requested |

Deploy via Chrome enterprise policy (`ExtensionSettings` → `force_installed` with a self-hosted CRX,
or `ExtensionInstallAllowlist` if published privately).

---

## Part 2 - the Cowork side

Colleague uploads the bundle to their Cowork session, plus `Emails.zip` if they have broker emails,
then asks Claude to run the Kato longlist from the bundle.

Stage 1 becomes:

```
python kato_ingest.py --config run.yaml --bundle kato_bundle_1708520_2026-08-17.zip
```

Everything after that is the existing pipeline, untouched. For a split capture, pass `--bundle` once
per part; ingest refuses to proceed unless every part is present.

### What it guarantees

* Reconstructs the exact tree `kato_fetch.py` writes, by calling the same `common.py` functions
  (`derive`, `sanitize`, `property_folder`, `ensure_image_limits`) rather than reimplementing them.
* **Refuses a mismatched bundle.** If the bundle's requirement id differs from `run.yaml`'s
  `kato_url`, it aborts rather than silently building a longlist for the wrong requirement.
* A property whose detail failed at capture is skipped entirely, not half-built, and is recorded in
  `_fetch_report.json` so it reaches the Gaps Report.
* No hard dependency on a compiled package: without `PIL` it skips the image size safety net and says
  so. imgix already caps images at 1200px/<500KB, so that net is normally a no-op.

### Enrichment (POIs and HGV drive-times)

Nothing to build. The toolkit already handles a network-dead sandbox via `web_enrich.py plan` →
run `web_enrich.html` in a browser → `web_enrich.py ingest`. Coordinates come free from Kato, and
offline city geocoding ships in the toolkit as `cities_dataset.json.gz`.

---

## Tests

```
python tests/make_test_bundle.py --tree "<a prior run dir>" --out fixture.zip
python helpers/kato_ingest.py --config <work>/run.yaml --bundle fixture.zip
python tests/verify_ingest.py --tree <work> --bundle fixture.zip --source "<prior run dir>"
node   tests/zip_test.mjs out.zip      # then read out.zip with Python's zipfile
```

`verify_ingest.py` asserts raw fidelity, self-consistency (`_derived.json` == `derive(raw, li)`),
media honesty (every URL `derive()` wants is on disk or recorded as a failure) and determinism (two
ingests are byte-identical).

`diff_trees.py` is the spec's full acceptance test and needs a live `kato_fetch.py` run to compare
against. Note that it will report differences on any tree containing manual `_corrections`.

### Known hazard, pre-existing

`kato_fetch.py:154` and `kato_ingest.py` both rewrite `_derived.json` unconditionally, so a re-run
destroys hand-made corrections. One property in a prior run carried
`_corrections: [{field: identity, before: "Phase 1B / CV23 9JR", after: "Unit 07 Symmetry Park Rugby / CV23 9LP"}]`,
which any re-fetch silently reverts. Worth fixing in the skill, separately from this bridge.
