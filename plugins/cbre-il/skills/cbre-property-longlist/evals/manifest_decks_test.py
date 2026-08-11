#!/usr/bin/env python3
"""manifest_decks_test.py - the page-binding net is never silently disarmed. (B14)

The region-label emitter rewrote work/vision/manifest.json with `"decks": []`, and nothing
ever put them back: _write_manifest only runs when there are decks or trackers to
interpret, and both are empty on every fully-interpreted resume pass. From the first
region-label exit-3 onward, vision_validate built an empty deck index, so page_no /
image_pages / plan_page / exclude_refs range checks, the source_file cross-check, the
twin-text reconciliation and the page-coverage warning ALL no-opped - permanently, for the
life of the work dir, with no diagnostic, because {"decks": []} is valid JSON and the
"manifest unreadable" warning never fires.

Both halves are asserted. Preserving the decks fixes today's path; the tripwire is the half
that cannot be silently bypassed the next time something rewrites that file. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import vision_validate as VV  # noqa: E402

RUN_SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")

DECKS = [{"region": "R1", "source_file": "deck.pdf",
          "pages": [{"page_no": 0}, {"page_no": 1}]}]


def _work(decks):
    d = Path(tempfile.mkdtemp(prefix="cbre_mdk_"))
    (d / "extract").mkdir()
    (d / "vision").mkdir()
    (d / "vision" / "manifest.json").write_text(
        json.dumps({"decks": decks}), encoding="utf-8")
    (d / "extract" / "R1_vision.json").write_text(json.dumps([
        {"park": "A", "__meta": {"page_no": 0, "image_pages": [0, 9]}}]), encoding="utf-8")
    return d


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # with decks, the range check FIRES (page 9 is not in the deck)
    errs, warns = VV.validate(_work(DECKS))
    ck(any("not a" in e and "rasterised page" in e for e in errs),
       f"with decks, the out-of-range image_pages check fires {ascii(str(errs[:1]))}")

    # with decks: [] it silently no-ops - and THAT must now be loud
    errs, warns = VV.validate(_work([]))
    ck(not errs, "with no decks the range check cannot fire (it is deck-gated)")
    ck(any("NO decks" in w for w in warns),
       f"...so a TRIPWIRE warning says the net is disarmed {ascii(str(warns[:1]))}")
    ck(any("SKIPPED" in w for w in warns),
       "the warning names the consequence, not just the condition")

    # a work dir with no vision files at all must stay silent
    d = Path(tempfile.mkdtemp(prefix="cbre_mdk0_"))
    (d / "extract").mkdir(); (d / "vision").mkdir()
    (d / "vision" / "manifest.json").write_text(json.dumps({"decks": []}), encoding="utf-8")
    errs, warns = VV.validate(d)
    ck(not any("NO decks" in w for w in warns),
       "no vision files -> no tripwire (nothing to validate, nothing disarmed)")

    # the region emitter must PRESERVE the decks it finds
    i = RUN_SRC.find('"region_labels": region_jobs')
    seg = RUN_SRC[max(0, i - 1400):i]
    # comments are not code - the explanation of the old bug legitimately quotes it
    code = "\n".join(ln for ln in seg.splitlines() if not ln.strip().startswith("#"))
    ck('"decks": []' not in code,
       "the region-label emitter no longer writes decks: []")
    ck("_prev_decks" in seg and 'get("decks")' in seg,
       "it reads the existing decks and carries them forward")

    # B51: the manifest must NOT hand a deck a field called `region`. It is the FILENAME-derived
    # cluster label, and three of eleven interpretation agents copied it into the record and
    # cited it to the deck's own page, on decks where the string appears nowhere. Renaming the
    # key is what makes that copy impossible; the legacy key must still READ so a warm work dir
    # is not forced through a fresh interpretation round.
    import interpret_prep as IP
    ip_src = Path(IP.__file__).read_text(encoding="utf-8")
    ck('"cluster_label": region' in ip_src,
       "interpret_prep emits cluster_label for a fresh deck entry")
    ck('"region": region' not in ip_src,
       "...and no longer emits a field called region")
    ck('entry["cluster_label"] = region' in ip_src and 'entry.pop("region"' in ip_src,
       "...and a REUSED entry is relabelled and stripped of the legacy key")
    ck("cluster_label_is_routing_only" in ip_src,
       "...and the entry flags the label as routing-only")

    import run as R
    ck(R._deck_label({"cluster_label": "A"}) == "A", "run._deck_label reads the new key")
    ck(R._deck_label({"region": "B"}) == "B",
       "run._deck_label falls back to a LEGACY manifest's region key")
    ck(R._deck_label({"cluster_label": "A", "region": "B"}) == "A",
       "run._deck_label prefers the new key when both are present")
    ck(R._deck_label({}) == "" and R._deck_label(None) == "",
       "run._deck_label degrades to '' on a malformed entry")

    vv_src = (Path(IP.__file__).parent / "vision_validate.py").read_text(encoding="utf-8")
    ck('d.get("cluster_label") or d.get("region")' in vv_src,
       "vision_validate indexes decks by the new key, legacy as fallback")

    if fails:
        print(f"\nMANIFEST DECKS TEST: FAIL ({len(fails)})")
        return 1
    print("\nMANIFEST DECKS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
