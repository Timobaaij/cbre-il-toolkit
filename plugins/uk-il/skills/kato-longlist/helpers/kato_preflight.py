#!/usr/bin/env python3
"""Stage 0 - decide WHICH fetch path this environment can actually use, and say so plainly.

WHY THIS EXISTS: the skill has two stage-1 paths - kato_fetch.py (Playwright + live network) and
kato_ingest.py (a browser-captured bundle, no network). Leaving the choice to the model's judgement
fails badly in Claude Cowork: it attempts the Playwright path, hits an ImportError or a silent network
timeout, and a non-technical colleague sees a traceback instead of "install this extension". So the
choice is MEASURED, not guessed, and the verdict is machine-readable.

It never raises on a missing capability - reporting one IS the job. Exit code is always 0 unless the
environment is so broken that even Python introspection failed.

Usage:
  python kato_preflight.py [--config run.yaml] [--dir <folder to scan for bundles>] [--json]
"""
import argparse
import glob
import json
import os
import platform
import sys

KATO_HOST = "https://agency.kato.app"
NEUTRAL_HOST = "https://api.github.com/zen"
TIMEOUT = 8


def probe_import(mod):
    try:
        m = __import__(mod)
        return True, str(getattr(m, "__version__", "") or "present")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}".split("\n")[0][:80]


def probe_url(url):
    """Short timeout on purpose: a sandbox usually BLACKHOLES rather than refusing, so a long
    timeout turns a capability check into a two-minute stall."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "kato-preflight"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code} (reachable)"      # a 4xx still proves egress
    except Exception as e:
        return False, f"{type(e).__name__}: {e}".split("\n")[0][:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--dir", default=None, help="folder to scan for bundles (default: config dir or cwd)")
    ap.add_argument("--json", action="store_true", help="print ONLY the json verdict")
    args = ap.parse_args()

    scan = args.dir or (os.path.dirname(os.path.abspath(args.config)) if args.config else os.getcwd())

    packages = {}
    for mod in ("requests", "yaml", "PIL", "openpyxl", "extract_msg", "fitz", "playwright"):
        packages[mod] = probe_import(mod)

    net_kato = probe_url(KATO_HOST)
    net_any = probe_url(NEUTRAL_HOST) if not net_kato[0] else (True, "not tested (Kato reachable)")

    bundles = sorted(glob.glob(os.path.join(scan, "kato_bundle_*.zip")))
    ingested = os.path.exists(os.path.join(scan, "properties", "_index.json"))

    can_fetch = bool(net_kato[0] and packages["playwright"][0])
    verdict = "DIRECT_FETCH_OK" if can_fetch else "BUNDLE_REQUIRED"
    action = None
    if can_fetch and ingested:
        action = ("properties/_index.json already exists - CONTINUE FROM STAGE 2/3. Re-run stage 1 "
                  "only to refresh, and note kato_fetch.py --refresh REWRITES _derived.json, which "
                  "discards any manual _corrections.")
    elif can_fetch and bundles:
        action = (f"Either stage 1-alt on the existing bundle ({os.path.basename(bundles[0])}, no "
                  f"re-download) or stage 1 kato_fetch.py for fresh data. Prefer the bundle unless "
                  f"the Kato listings have changed since it was captured.")
    elif can_fetch:
        action = "Run stage 1: kato_fetch.py"
    elif ingested and not bundles:
        action = "Bundle already ingested (properties/_index.json exists) - continue from stage 2/3"
    elif bundles:
        action = f"Run stage 1-alt: kato_ingest.py --bundle {os.path.basename(bundles[0])}"
    elif ingested:
        action = "Bundle already ingested (properties/_index.json exists) - continue from stage 2/3"
    else:
        action = "DELIVER THE CAPTURE EXTENSION TO THE USER - no bundle present and Kato is unreachable"

    degradations = []
    if not packages["extract_msg"][0]:
        degradations.append("extract_msg missing -> SKIP stage 2 (.msg parsing). Stage 3 does not need "
                            "it: make_facts.py reads only properties/*/_derived.json, and the Kato "
                            "in-app threads that carry most rents are already in the bundle.")
    if not packages["PIL"][0]:
        degradations.append("PIL missing -> kato_ingest skips the image size safety net. Normally a "
                            "no-op, since imgix already caps images at 1200px/<500KB.")
    if not packages["fitz"][0]:
        degradations.append("pymupdf (fitz) missing -> stage 7d site-plan montages unavailable. The "
                            "toolkit vendors a manylinux wheel; install it from that local file "
                            "(works with no network).")
    if not packages["openpyxl"][0]:
        degradations.append("openpyxl missing -> stage 6 client Excel unavailable.")
    if not net_kato[0]:
        degradations.append("No network -> the toolkit spine's --geocode/--pois/--osrm/--regions "
                            "cannot run live. Use its web_enrich.py plan -> run the fetcher page in a "
                            "browser -> web_enrich.py ingest handoff. Coordinates come free from Kato.")

    result = {
        "verdict": verdict,
        "action": action,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.machine()}",
        "network": {"kato": {"ok": net_kato[0], "detail": net_kato[1]},
                    "general": {"ok": net_any[0], "detail": net_any[1]}},
        "packages": {k: {"ok": v[0], "detail": v[1]} for k, v in packages.items()},
        "bundles_found": [os.path.basename(b) for b in bundles],
        "already_ingested": ingested,
        "degradations": degradations,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("=" * 72)
    print(f"KATO PREFLIGHT   python {result['python']}   {result['platform']}")
    print("=" * 72)
    print(f"  network -> {KATO_HOST:34} {'OK  ' if net_kato[0] else 'DEAD'}  {net_kato[1]}")
    if not net_kato[0]:
        print(f"  network -> {'general internet':34} {'OK  ' if net_any[0] else 'DEAD'}  {net_any[1]}")
    print("  packages:")
    for k, (ok, detail) in packages.items():
        print(f"    {'OK  ' if ok else 'MISS'}  {k:14} {detail}")
    print(f"  bundles in {scan}: {result['bundles_found'] or 'none'}")
    print(f"  already ingested: {ingested}")
    if degradations:
        print("\n  DEGRADATIONS:")
        for d in degradations:
            print(f"    - {d}")
    print(f"\n  VERDICT: {verdict}")
    print(f"  ACTION : {action}")
    print("=" * 72)

    try:
        with open(os.path.join(scan, "_preflight.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    except Exception:
        pass


if __name__ == "__main__":
    main()
