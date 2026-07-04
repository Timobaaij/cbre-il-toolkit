#!/usr/bin/env python3
"""render_qa.py - the MECHANICAL half of G-visual.

The judgement half (does it look like a CBRE deliverable?) is an isolated Sonnet
reviewer driven by the Claude Preview MCP - see reference/visual-qa.md. This
script does the deterministic part:

  * if Playwright is installed: load the built HTML headless, assert the rendered
    .card count == PROPS length, capture console errors (any = fail), and save
    grid/modal/map screenshots to <out>/render/.
  * otherwise: write a .claude/launch.json next to the file and print the exact
    Preview-MCP steps the orchestrator should run, plus the DOM assertions.

The reference dashboard embeds ~30 base64 images, so a full-page screenshot can
be heavy; the orchestrator may prefer DOM assertions (preview_eval) over a
screenshot when the renderer is slow.

CLI:
  python render_qa.py <built.html> [--out render/]   (--out-dir is an alias of --out)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ASSERTIONS = """\
Preview-MCP procedure (orchestrator runs these; an isolated Sonnet reviewer judges the PNGs):
  1. preview_start a static server for the built file's directory.
  2. preview_eval: navigate to the file, wait ~3s.
  3. preview_eval: assert document.querySelectorAll('.card').length === PROPS.length
  4. preview_eval('openModal(1)')  -> screenshot the detail modal
  5. preview_eval("switchView('map')") -> screenshot the map. Toggle a POI layer only
     if meta.enrichment.pois, an isochrone only if meta.enrichment.osrm (opt-in extras).
  6. preview_console_logs level=error  -> MUST be empty, except blocked network fetches
     to tile/Overpass/OSRM hosts in a sandboxed preview (environment, not a defect -
     grey map tiles in a sandbox are an [ENV] note, never a block; see visual-qa.md).
  7. Save grid.png / modal.png / map.png and have the isolated reviewer judge them per
     reference/visual-qa.md, writing reviews/G-visual.md ending VERDICT: <green|amber|red>.
"""


def _is_env_error(text: str) -> bool:
    """A console error from the OFFLINE environment (map tiles / routing host
    unreachable, favicon), not a code defect - it must not hard-BLOCK G-visual,
    matching the tile/OSRM [ENV] allowance elsewhere (audit S6-16)."""
    t = (text or "").lower()
    return any(k in t for k in (
        "tile", "openstreetmap", "osm.org", "osrm", "unpkg", "favicon",
        "err_internet", "err_network", "err_name_not_resolved", "err_connection",
        "err_address", "failed to fetch", "net::", "load failed"))


def playwright_check(html: Path, out: Path) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return -1
    out.mkdir(parents=True, exist_ok=True)
    errors, cards, props = [], None, None
    # The WHOLE browser session is guarded: 'pip install playwright' without
    # 'playwright install' makes chromium.launch() raise. That state must fall
    # through to the Preview-MCP path with a classified STATUS, never die as a raw
    # traceback with no STATUS line (the orchestrator keys on STATUS).
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 1000})
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(html.resolve().as_uri())
            pg.wait_for_timeout(3000)
            cards = pg.eval_on_selector_all(".card", "els => els.length")
            props = pg.evaluate("typeof PROPS!=='undefined'?PROPS.length:-1")
            pg.screenshot(path=str(out / "grid.png"), full_page=False)
            try:
                pg.evaluate("openModal(1)"); pg.wait_for_timeout(800)
                pg.screenshot(path=str(out / "modal.png"))
                pg.evaluate("closeModal && closeModal()")
            except Exception:
                pass
            try:
                pg.evaluate("switchView('map')"); pg.wait_for_timeout(1500)
                pg.screenshot(path=str(out / "map.png"))
            except Exception:
                pass
            b.close()
    except Exception as e:
        print(f"(Playwright present but unusable: {type(e).__name__}: {str(e).splitlines()[0][:160]})")
        return -1  # browsers not installed / launch failed -> Preview-MCP path
    real_errors = [e for e in errors if not _is_env_error(e)]
    env_errors = [e for e in errors if _is_env_error(e)]
    ok = (cards == props) and not real_errors
    print(f"[{'PASS' if ok else 'FAIL'}] cards={cards} props={props} "
          f"consoleErrors={len(real_errors)} (env-allowed={len(env_errors)})")
    if real_errors:
        for e in real_errors[:5]:
            print("   console error:", e)
    print(f"screenshots -> {out}")
    print(f"STATUS: {'ALL-PASS' if ok else 'BLOCKED'}")
    return 0 if ok else 1


def static_dom_floor(html: str) -> list[tuple[bool, str]]:
    """Browser-free structural FLOOR for G-visual, used when NO renderer (Playwright or the
    Preview MCP) is available - the real Cowork constraint. It confirms the built file is a
    complete, openable, token-clean dashboard (all three data blocks, no unreplaced config
    tokens, a non-empty PROPS whose every photo is an embedded data: URI, the map + CBRE
    chrome intact) - a mechanical proxy for "it will render". A structurally BROKEN file
    (leaked token / empty PROPS / a non-embedded photo) fails here and BLOCKS regardless of
    rendering. It does NOT judge appearance, so a sound file that reaches only this floor is
    DEGRADED on the visual dimension - label the run so, never call it a clean visual pass."""
    import re
    out: list[tuple[bool, str]] = []

    def chk(ok, label):
        out.append((bool(ok), label))

    for blk in ("PROPS", "POIS", "REGIONS"):
        chk(f"const {blk} = " in html, f"data block const {blk} present")
    leaked = sorted(set(re.findall(r"\{\{\s*[a-zA-Z0-9_]+\s*\}\}", html)))
    chk(not leaked, "no unreplaced {{config}} tokens" + (f" (leaked {leaked[:4]})" if leaked else ""))
    m = re.search(r"const PROPS = (.*?);(?:\n|$)", html, re.DOTALL)
    props = None
    if m:
        try:
            props = json.loads(m.group(1))
        except Exception:
            props = None
    chk(isinstance(props, list) and len(props) > 0,
        f"PROPS parses as a non-empty array ({len(props) if isinstance(props, list) else 'UNPARSEABLE'})")
    if isinstance(props, list) and props:
        # a malformed entry (non-object, or no embedded photo) is a floor FAILURE, never a
        # crash - the floor must classify a broken file from ANY source, not just clean output
        bad = []
        for p in props:
            if not isinstance(p, dict):
                bad.append("<non-object>")
            elif not (isinstance(p.get("photo"), str) and p["photo"].startswith("data:image/")):
                bad.append(p.get("id"))
        chk(not bad, "every property is an object with an embedded data: URI photo"
            + (f" (bad: {bad[:4]})" if bad else ""))
    chk(("leaflet" in html.lower()) or ("L.map(" in html), "map (Leaflet) script present")
    chk("CBRE" in html, "CBRE branding chrome present")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--out", "--out-dir", dest="out", default="render",
                    help="output dir for screenshots (--out-dir is an alias, matching the sibling scripts)")
    args = ap.parse_args()
    html = Path(args.html)
    sys.stdout.reconfigure(encoding="utf-8")
    rc = playwright_check(html, Path(args.out))
    if rc == -1:
        launch = {"version": "0.0.1", "configurations": [{
            "name": "longlist-preview", "runtimeExecutable": "python",
            "runtimeArgs": ["-m", "http.server", "8799", "--directory", str(html.parent.resolve())],
            "port": 8799}]}
        # next to the built file (as documented) - NOT the CWD, which once littered a
        # stale launch.json pointing at a dead temp dir into the skill root itself
        cl = html.resolve().parent / ".claude"; cl.mkdir(exist_ok=True)
        (cl / "launch.json").write_text(json.dumps(launch, indent=2), encoding="utf-8")
        print("Playwright unavailable - G-visual runs via the Claude Preview MCP instead "
              "(available in Cowork). This is NOT a reason to skip G-visual - run the steps below.\n")
        # browser-free structural FLOOR: even with no renderer at all, a broken file
        # (leaked token / empty PROPS / non-embedded photo) is caught and BLOCKS here.
        # Guarded so a malformed file can NEVER kill the STATUS line the orchestrator keys on.
        try:
            floor = static_dom_floor(html.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            floor = [(False, f"static structural floor could not run ({type(e).__name__})")]
        print("Static structural floor (browser-free - the last-resort mechanical check):")
        for ok, label in floor:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        print()
        print(ASSERTIONS)
        print(f"(wrote .claude/launch.json serving {html.parent})")
        if not all(ok for ok, _ in floor):
            # a structurally broken build is wrong no matter how it renders - block it
            print("\nSTATUS: BLOCKED (static structural floor failed - the built file is "
                  "broken; fix it before any visual review)")
            sys.exit(1)
        # a visible, machine-readable status so the skipped-gate state is never silent
        print("\nSTATUS: NEEDS-PREVIEW-MCP (static structural floor PASSED; run the Preview-MCP "
              "procedure above for the visual judgement. If NO renderer is available "
              "(no Playwright AND no Preview MCP), the floor is the mechanical proof - mark the "
              "run DEGRADED on the visual dimension, never a clean visual pass)")
        sys.exit(0)
    sys.exit(rc)


if __name__ == "__main__":
    main()
