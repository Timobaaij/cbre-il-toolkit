#!/usr/bin/env python3
"""f14_filename_sanitise_test.py - the client name reaches FILENAMES sanitised, and nothing else. (F14)

The Stage-0 form takes the client name as free text and the spine hands it straight to
deliver.py as --slug. deliver composed `<slug>_Gaps_Report.md`, `<slug>_Source_Ledger.xlsx` and
`<slug>_Longlist.xlsx` from it verbatim, so a name ending in a full stop produced a double dot
before the extension and a name with spaces produced spaced filenames in the broker's output
folder (both observed on a live run).

WHAT THIS PINS
  * deliver.safe_slug(): runs of non-alphanumerics collapse to ONE underscore, leading and
    trailing underscores go, an empty result falls back to a non-empty constant, and it is
    IDEMPOTENT - final_gate derives the slug back OUT of the Gaps Report filename and re-feeds
    it, so a second pass must not rename anything.
  * the artefacts deliver writes are named from the sanitised slug, while the Gaps Report
    TITLE and the marker keep the broker's exact text: the name on the page is data.
  * an explicit --filename is honoured byte-for-byte (the spine composes it and looks the
    dashboard up under that exact name; run.py owns applying safe_slug there).
  * every name produced still matches intake._OWN_OUTPUT, so a re-run in the same folder still
    refuses to re-ingest its own deliverables.
Offline; a real deliver.py subprocess on a tiny canonical.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import deliver as D  # noqa: E402
import intake as I  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon():
    return {"meta": {"client": "Example Client B.V.", "units": {"area": "sq ft"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "properties": [{"id": 1, "park": "Alpha", "city": "Sometown", "country": "GB",
                            "warehouseArea": 120000}],
            "pois": [], "regions": {}}


def main() -> int:
    print("== safe_slug(): the unit ==")
    cases = {
        "Example Client B.V.": "Example_Client_B_V",
        "Example Client Ltd.": "Example_Client_Ltd",
        "Example  Client": "Example_Client",
        "Example/Client:2026?": "Example_Client_2026",
        "  spaced  ": "spaced",
        "Longlist": "Longlist",
        "plain": "plain",
        "": D.SLUG_FALLBACK, "   ": D.SLUG_FALLBACK, "...": D.SLUG_FALLBACK, None: D.SLUG_FALLBACK,
    }
    for raw, want in cases.items():
        got = D.safe_slug(raw)
        ck(got == want, f"safe_slug({raw!r}) == {want!r} (got {got!r})")
        ck(re.fullmatch(r"[A-Za-z0-9_]+", got) is not None, f"...and is a clean filename component")
        ck(D.safe_slug(got) == got, f"...and is idempotent (final_gate re-feeds the derived slug)")
    ck(D.SLUG_FALLBACK and D.SLUG_FALLBACK == D.safe_slug(D.SLUG_FALLBACK),
       "the fallback is itself a fixed point")

    print()
    print("== a real delivery with an awkward client name ==")
    raw_slug = "Example Client B.V."
    safe = D.safe_slug(raw_slug)
    with tempfile.TemporaryDirectory(prefix="cbre_f14_") as td:
        work = Path(td) / "work"
        work.mkdir()
        (work / "canonical.json").write_text(json.dumps(_canon()), encoding="utf-8")
        (work / "built.html").write_text("<html>dash</html>", encoding="utf-8")
        (work / "source_ledger.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        outd = Path(td) / "out"

        def _deliver(*extra):
            return subprocess.run(
                [sys.executable, str(HELPERS / "deliver.py"),
                 "--canonical", str(work / "canonical.json"), "--html", str(work / "built.html"),
                 "--ledger", str(work / "source_ledger.csv"), "--out-dir", str(outd),
                 "--marker-dir", str(work), "--slug", raw_slug, *extra],
                capture_output=True, text=True, errors="replace")

        p = _deliver()
        ck(p.returncode == 0, f"deliver completes {ascii((p.stdout + p.stderr)[-160:])}")
        names = sorted(f.name for f in outd.iterdir())
        print("    produced:", names)
        ck(f"CBRE_Property_Dashboard_{safe}.html" in names,
           "the dashboard (no --filename) is named from the sanitised slug")
        ck(f"{safe}_Gaps_Report.md" in names, "the Gaps Report is named from the sanitised slug")
        ck(any(n.startswith(f"{safe}_Source_Ledger.") for n in names),
           "the Source Ledger is named from the sanitised slug")
        ck(any(n.startswith(f"{safe}_Longlist.") for n in names),
           "the Longlist is named from the sanitised slug")
        for n in names:
            ck(" " not in n and ".." not in n and not n.startswith("."),
               f"no space, no double dot, no leading dot in {n!r}")
            ck(I._OWN_OUTPUT.search(n) is not None,
               f"intake._OWN_OUTPUT still recognises {n!r} as the skill's own output")
        gaps = (outd / f"{safe}_Gaps_Report.md").read_text(encoding="utf-8")
        ck(gaps.splitlines()[0] == f"# {raw_slug} - Longlist Gaps Report",
           f"the Gaps Report TITLE keeps the broker's exact text ({gaps.splitlines()[0]!r})")
        marker = json.loads((work / D.MARKER_NAME).read_text(encoding="utf-8"))
        ck(marker.get("slug") == safe and marker.get("client") == raw_slug,
           "the marker records both the filename slug and the exact client text")
        ck(D.delivery_complete(outd, work), "delivery_complete() is True against the sanitised names")

        # final_gate's round trip: slug derived from the report name, fed back in, changes nothing
        derived = f"{safe}_Gaps_Report.md"[: -len("_Gaps_Report.md")]
        ck(D.safe_slug(derived) == derived,
           "final_gate's derived slug is a fixed point (a re-delivery writes no second report)")
        before = set(names)
        p2 = subprocess.run(
            [sys.executable, str(HELPERS / "deliver.py"),
             "--canonical", str(work / "canonical.json"), "--html", str(work / "built.html"),
             "--ledger", str(work / "source_ledger.csv"), "--out-dir", str(outd),
             "--marker-dir", str(work), "--slug", derived],
            capture_output=True, text=True, errors="replace")
        ck(p2.returncode == 0 and set(f.name for f in outd.iterdir()) == before,
           "re-delivering with the derived slug overwrites in place, adds no file")

        # an explicit --filename is honoured byte-for-byte
        p3 = _deliver("--filename", "Custom Name.html")
        ck(p3.returncode == 0 and (outd / "Custom Name.html").exists(),
           "an explicit --filename is honoured exactly (the spine composes and looks it up)")

    print()
    print("== the wiring, read off the source ==")
    src = (HELPERS / "deliver.py").read_text(encoding="utf-8", errors="replace")
    body = src.split("def main()", 1)[-1]
    ck("slug = safe_slug(args.slug)" in body, "main() sanitises once, up front")
    ck('f"{args.slug}_' not in body, "no artefact name is composed from the RAW slug any more")
    ck("gaps_report(canonical, args.slug" in body, "the report title is still built from the RAW slug")
    fg = (HELPERS / "final_gate.py").read_text(encoding="utf-8", errors="replace")
    ck('_gf.name[: -len("_Gaps_Report.md")]' in fg,
       "final_gate still derives the slug from the report filename (the round trip above is live)")

    print()
    print("== the SCAFFOLD: project.yaml from a free-text client name (2026-09-26, fix 3.19) ==")
    import yaml  # noqa: E402
    inv = {"clusters": {}, "present_types": [], "emails": []}
    for raw, want in (("Example Ltd.", "CBRE_Property_Dashboard_Example_Ltd.html"),
                      ("Acme Retail", "CBRE_Property_Dashboard_Acme_Retail.html")):
        cfg = yaml.safe_load(I.scaffold_yaml(inv, raw))
        fn = cfg["output"]["filename"]
        ck(fn == want, f"scaffold filename for {raw!r} is {want!r} (got {fn!r})")
        ck(cfg["client"]["name"] == raw, f"...and client.name loads back verbatim ({cfg['client']['name']!r})")
    nasty = 'A/B: C*?"<>|'
    cfg = yaml.safe_load(I.scaffold_yaml(inv, nasty))
    fn = cfg["output"]["filename"]
    ck(not re.search(r'[<>:"/\\|?*]', fn) and ".." not in fn and " " not in fn,
       f"a name full of Windows-illegal characters gives a clean filename ({fn!r})")
    ck(I._OWN_OUTPUT.search(fn) is not None, "...which intake._OWN_OUTPUT still recognises")
    ck(cfg["client"]["name"] == nasty, "...while client.name keeps the exact text")
    for raw in ("Acme: Retail #1", "#1 Logistics", "[Group] {Holdings}", "Zo\u00eb & S\u00f8n: \u00c5B"):
        try:
            got = yaml.safe_load(I.scaffold_yaml(inv, raw))["client"]["name"]
        except Exception as e:  # noqa: BLE001
            got = f"<yaml error {type(e).__name__}>"
        ck(got == raw, f"client.name {raw!r} is valid YAML and loads back byte-identical (got {got!r})")
    ck(yaml.safe_load(I.scaffold_yaml(inv, ""))["output"]["filename"]
       == f"CBRE_Property_Dashboard_{D.SLUG_FALLBACK}.html",
       "an empty name falls back to the same constant deliver uses")
    # an EXISTING, hand-edited project.yaml is never rewritten by a re-run of intake (only its
    # clusters block may be merged, and there is nothing to merge in an empty folder)
    with tempfile.TemporaryDirectory(prefix="cbre_f14y_") as td:
        inputs, work = Path(td) / "in", Path(td) / "work"
        inputs.mkdir()
        work.mkdir()
        hand = ('setup:\n  confirmed: true\nclient:\n  name: Example Ltd.\noutput:\n'
                '  filename: "Hand Picked Name.html"\ninputs:\n  clusters: {}\n')
        (work / "project.yaml").write_bytes(hand.encode("utf-8"))
        subprocess.run([sys.executable, str(HELPERS / "intake.py"), str(inputs),
                        "--out-dir", str(work), "--client", "Example Ltd."],
                       capture_output=True, text=True, errors="replace")
        ck((work / "project.yaml").read_bytes() == hand.encode("utf-8"),
           "a hand-edited existing project.yaml is byte-identical after intake re-runs")

    print()
    if FAILS:
        print(f"F14 FILENAME SANITISE TEST: FAIL ({len(FAILS)})")
        return 1
    print("F14 FILENAME SANITISE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
