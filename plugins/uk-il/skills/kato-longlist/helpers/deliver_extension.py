#!/usr/bin/env python3
"""Stage 0b - hand the user the capture extension when this environment cannot reach Kato.

WHY: in Cowork the model cannot fetch anything, so the ONLY way forward is for the human to capture the
requirement in their own browser. That means the extension has to travel INSIDE the skill package and
be deliverable in one step, with instructions a non-technical colleague can follow. Telling them "use
the Chrome extension" without giving them the file is a dead end.

It rebuilds the zip from source each time rather than shipping a stale copy, so the delivered extension
always matches the helpers in this skill.

Usage:
  python deliver_extension.py --out <folder to place the zip and instructions in>
  python deliver_extension.py --out . --source <path to extension/ dir>
"""
import argparse
import os
import shutil
import sys
import zipfile

INSTRUCTIONS = """# Capture your Kato longlist (5 minutes, once)

Claude cannot reach Kato from here: this environment has no access to the internet, so it cannot sign
in on your behalf. You capture the data in your own browser instead, then hand Claude one file.

## 1. Install the extension (once)

1. Unzip `kato-capture-extension.zip` somewhere permanent, for example `C:\\Users\\<you>\\KatoCapture\\`.
   Do not run it from inside the zip.
2. In Chrome, go to `chrome://extensions`
3. Turn on **Developer mode** (top right)
4. Click **Load unpacked** and choose the folder you unzipped
5. Pin the green **K** icon to your toolbar

If Developer mode is switched off and you cannot turn it on, it is blocked by IT policy. Send them the
`README.md` inside the zip: it lists exactly what the extension can and cannot do.

## 2. Capture the requirement

1. Open the Kato requirement you want. The address must contain `/requirements/<number>/`
2. Click the **K** icon. A capture tab opens
3. Leave **Include brochures and documents** ticked, unless you are told otherwise. Site plans need them
4. If you were told to split the file, enter a size in MB. Otherwise leave it at 0
5. Click **Capture and save bundle** and choose where to save
6. **Keep the tab open until it finishes.** It shows progress and lists anything that failed

You will get a file called `kato_bundle_<number>_<date>.zip`. A large London requirement can be around
300MB, so give it a few minutes.

## 3. Hand it back

Upload that zip here and say: **run the Kato longlist from this bundle**.

If you also have broker emails, upload `Emails.zip` (Outlook `.msg` files) too. It is optional: most
broker rents are posted on the Kato message threads, which the capture already includes.

### If something goes wrong

- **"Cannot reach the Kato tab"** - reload the Kato page and click the icon again. This happens when the
  extension was installed after the tab was already open.
- **"Could not reach the Kato API"** - you have probably been signed out. Sign in again and retry.
- **The upload is rejected as too large** - capture again with a split size of 100 MB, then upload each
  part. Claude needs every part.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder to write the zip + instructions into")
    ap.add_argument("--source", default=None, help="path to the extension/ source dir")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        args.source,
        os.path.join(here, os.pardir, "assets", "extension"),
        os.path.join(here, os.pardir, os.pardir, os.pardir, "Kato Run", "Cowork Test",
                     "kato-cowork-bridge", "extension"),
    ]
    source = next((os.path.abspath(c) for c in candidates
                   if c and os.path.exists(os.path.join(c, "manifest.json"))), None)
    if not source:
        raise SystemExit("Could not find the extension source (needs a manifest.json). Pass --source.")

    os.makedirs(args.out, exist_ok=True)
    zip_path = os.path.join(args.out, "kato-capture-extension.zip")

    # Rebuilt from source every time, so a delivered extension can never lag the helpers.
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(source):
            for f in files:
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, source).replace("\\", "/"))
                n += 1
        readme = os.path.join(source, os.pardir, "README.md")
        if os.path.exists(readme):
            z.write(readme, "README.md")
            n += 1

    inst_path = os.path.join(args.out, "HOW-TO-CAPTURE-KATO.md")
    with open(inst_path, "w", encoding="utf-8") as fh:
        fh.write(INSTRUCTIONS)

    size = os.path.getsize(zip_path)
    print(f"extension  -> {zip_path}  ({n} files, {size/1024:.0f} KB)")
    print(f"instructions -> {inst_path}")
    print("\nDELIVER BOTH FILES TO THE USER, then stop and wait for their bundle.")


if __name__ == "__main__":
    main()
